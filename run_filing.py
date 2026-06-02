# /// script
# dependencies = [
#   "pypdf",
#   "cryptography",
# ]
# ///

import os
import json
import re
import urllib.request
import urllib.error
import shutil
import argparse
import datetime
import hashlib
from pathlib import Path
from urllib.parse import urlparse

# ============================================================
# PRIVACY FIREWALL
# All LLM calls route ONLY to local Ollama (localhost:11434).
# Tax data is NEVER sent to cloud APIs.
# ============================================================

def _assert_local_host(url: str) -> None:
    """Hard-abort if the Ollama URL is not localhost."""
    host = urlparse(url).hostname or ""
    if host not in ("localhost", "127.0.0.1", "::1"):
        raise RuntimeError(
            f"[PRIVACY VIOLATION] Refusing to send tax data to external host: {url}\n"
            "Only a local Ollama instance is permitted."
        )

# Configuration
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
WORKSPACE_DIR = Path(__file__).parent.resolve()
PROCESSED_DATA_DIR = WORKSPACE_DIR / "processed_data"
FINAL_OUTPUTS_DIR = WORKSPACE_DIR / "final_outputs"
CANDIDATES_DIR = FINAL_OUTPUTS_DIR / "candidates"
RUN_LOG_DIR = WORKSPACE_DIR / "run_log"
SKILLS_DIR = WORKSPACE_DIR / ".agents" / "skills"

# Default Model
TAX_PREP_MODEL = "gemma4:latest"

def get_installed_models() -> list:
    """Fetch list of installed models from local Ollama instance."""
    url = f"{OLLAMA_HOST}/api/tags"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3.0) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return [m["name"] for m in res_data.get("models", [])]
    except Exception:
        return []

def resolve_model(target_model: str, default_fallback: str = "gemma2:9b") -> str:
    """Check if target_model is installed, fallback if not."""
    installed = get_installed_models()
    if not installed:
        return target_model
    for m in installed:
        if m.lower() == target_model.lower():
            return m
    target_clean = target_model.split(":")[0].lower()
    for m in installed:
        m_clean = m.split(":")[0].lower()
        if m_clean == target_clean:
            return m
    
    # Try any gemma
    gemma_models = [m for m in installed if "gemma" in m.lower() and "medical" not in m.lower() and "audit" not in m.lower()]
    if gemma_models:
        return gemma_models[0]
    return default_fallback

def query_ollama(model: str, system_prompt: str, user_prompt: str, temp: float = 0.1, num_ctx: int = 8192) -> str:
    """Query local Ollama with run isolation. PRIVACY: Hard-errors if host is not localhost."""
    url = f"{OLLAMA_HOST}/api/chat"
    _assert_local_host(url)
    print(f"  [PRIVACY] Local Gemma only — {model} @ {OLLAMA_HOST}")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "stream": False,
        "options": {
            "num_ctx": num_ctx,
            "temperature": temp
        }
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return res_data["message"]["content"]
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            pass
        print(f"\n[ERROR] Ollama API returned HTTP {e.code}: {e.reason}")
        if body:
            print(f"Details: {body}")
        raise
    except urllib.error.URLError as e:
        print(f"\n[ERROR] Failed to connect to Ollama at {OLLAMA_HOST}.")
        print("Please make sure Ollama is running and accessible.")
        print(f"Details: {e}")
        raise

def extract_names(tax_data: dict) -> list[str]:
    """Helper to extract taxpayer and spouse names from tax return data."""
    names = []
    w2_list = tax_data.get("w2_wages") or []
    if not isinstance(w2_list, list):
        w2_list = [w2_list]
    for item in w2_list:
        tp = item.get("taxpayer")
        if tp and tp not in names:
            names.append(tp)
            
    fd = tax_data.get("filing_details") or {}
    for key in ["taxpayer_name", "spouse_name", "names", "taxpayer", "spouse", "primary_taxpayer"]:
        val = fd.get(key)
        if val:
            if isinstance(val, list):
                for v in val:
                    if v and v not in names:
                        names.append(v)
            elif isinstance(val, str) and val not in names:
                names.append(val)
                
    return [n for n in names if n.strip()]

def score_report(text: str) -> tuple[int, list[str], list[str]]:
    """Score candidate report against a structural completeness rubric."""
    text_lower = text.lower()
    score = 0
    passed_rubrics = []
    matched_negatives = []

    # 1. Safe Harbor evaluation (10 pts)
    if any(k in text_lower for k in ["safe harbor", "110%", "underpayment", "form 2210", "2210"]):
        score += 10
        passed_rubrics.append("safe_harbor_evaluation")

    # 2. Late payment penalty (10 pts)
    if any(k in text_lower for k in ["failure-to-pay", "failure to pay", "6651", "0.5%"]):
        score += 10
        passed_rubrics.append("late_payment_penalty")

    # 3. Interest calculation (10 pts)
    if any(k in text_lower for k in ["interest", "6621", "compound", "daily"]):
        score += 10
        passed_rubrics.append("interest_calculation")

    # 4. Passive loss analysis (15 pts)
    if any(k in text_lower for k in ["passive", "8582", "phase-out", "phase out", "suspended", "suspension"]):
        score += 15
        passed_rubrics.append("passive_loss_analysis")

    # 5. MACRS depreciation (15 pts)
    if any(k in text_lower for k in ["27.5", "macrs", "straight-line", "mid-month", "depreciation"]):
        score += 15
        passed_rubrics.append("macrs_depreciation")

    # 6. Hobby loss / Schedule C assessment (10 pts)
    if any(k in text_lower for k in ["hobby", "183", "profit motive", "schedule c"]):
        score += 10
        passed_rubrics.append("hobby_loss_assessment")

    # 7. Tax minimization strategies (15 pts)
    if any(k in text_lower for k in ["strategy", "str loophole", "short-term rental", "reps", "real estate professional", "savings"]):
        score += 15
        passed_rubrics.append("tax_minimization_strategies")

    # 8. Missing docs / open questions (15 pts)
    if any(k in text_lower for k in ["missing", "requested documents", "open questions", "questions for", "still needed"]):
        score += 15
        passed_rubrics.append("missing_documents_section")

    # Negatives: these rules only apply if the return is late — flag if incorrectly cited
    negatives = ["failure-to-file penalty", "5% per month"]
    for neg in negatives:
        if neg in text_lower:
            score -= 5
            matched_negatives.append(neg)

    return max(0, min(score, 100)), passed_rubrics, matched_negatives


def build_system_prompt(tax_data: dict, current_date: str, tax_year: int) -> str:
    """Build a data-driven system prompt from actual extracted tax data."""
    filing = tax_data.get("filing_details", {})
    w2 = tax_data.get("w2_summary", {})
    rental = tax_data.get("rental_property", {})
    side_biz = tax_data.get("side_business", {})

    filing_status = filing.get("filing_status", "unknown")
    prior_tax = filing.get("prior_year_total_tax")
    total_wages = w2.get("total_w2_wages")
    total_withheld = w2.get("total_federal_withheld")

    def fmt(val):
        if isinstance(val, (int, float)):
            return f"${val:,.2f}"
        return str(val) if val else "not available"

    lines = []
    if total_wages:
        lines.append(f"- Total W-2 wages: {fmt(total_wages)}")
    if total_withheld:
        lines.append(f"- Federal withholding: {fmt(total_withheld)}")
    if prior_tax:
        lines.append(f"- Prior year tax liability: {fmt(prior_tax)}")
    net_rental = rental.get("net_reported_loss") or rental.get("net_profit_or_loss")
    if net_rental is not None:
        lines.append(f"- Rental net loss/profit: {fmt(net_rental)}")
    net_biz = side_biz.get("net_reported_loss") or side_biz.get("net_profit_or_loss")
    if net_biz is not None:
        lines.append(f"- Side business net loss/profit: {fmt(net_biz)}")

    data_context = "\n".join(lines) if lines else "(see full tax data below)"

    return f"""You are the Tax Prep Agent (Advisor). Generate a premium Tax Preparation Report & Action Plan based on the actual extracted tax data.

CRITICAL CONSTANTS:
- Current Date of Review: {current_date}
- Tax Year Under Review: {tax_year}
- Filing Status: {filing_status}

KEY DATA SUMMARY:
{data_context}

REQUIRED REPORT STRUCTURE — address each section using the actual data provided:

1. EXECUTIVE SUMMARY
   Summarize key income sources, payment status, and top recommendations.

2. ESTIMATED TAX & SAFE HARBOR EVALUATION (IRC § 6654)
   - Determine if this is a high-income filer (prior year AGI > $150k → 110% safe harbor applies).
   - Compute the safe harbor threshold and compare against total payments (withholding + estimated).
   - State whether Form 2210 underpayment penalty applies.

3. LATE PAYMENT PENALTIES & INTEREST
   - Calculate remaining balance (estimated total tax minus total payments).
   - Failure-to-Pay Penalty (IRC § 6651(a)(2)): 0.5%/month on unpaid balance from April 15.
   - Interest (IRC § 6621): daily compounding at federal short-term rate + 3%.
   - Present a liability summary table: principal due, penalty, interest, total balance.

4. COMPLIANCE REVIEW & RECOMMENDED ACTIONS
   - Passive Loss (IRC § 469): Apply MAGI phase-out to rental net income/loss. State whether losses must be suspended on Form 8582.
   - MACRS Depreciation: Verify 27.5-year GDS straight-line, mid-month convention, land exclusion.
   - Hobby Loss (IRC § 183): Assess side business loss history. Flag hobby classification risk and profit-motive steps.

5. TAX MINIMIZATION STRATEGIES
   Calculate potential savings at the taxpayer's actual marginal rate:
   - STR Loophole (Treas. Reg. § 1.469-1T(e)(3)(ii)(A)): if rental loss and property could qualify.
   - REPS Spouse Strategy (IRC § 469(c)(7)): if a spouse could meet the 750-hour / 50% tests.
   - Hobby-to-Business Restructuring: dollar benefit of defending Schedule C losses.

6. MISSING DOCUMENTS & OPEN QUESTIONS
   List any gaps in the data and questions for the taxpayer.

7. NEXT STEPS & ACTION ITEMS
   Actionable checklist to reach "ready to file."

Base ALL calculations on the provided tax data. Do not invent or substitute figures.
Output professional markdown only (no raw JSON)."""

def main():
    parser = argparse.ArgumentParser(description="Filing-Only Multi-Run Tax Swarm Execution Engine")
    parser.add_argument("--runs", type=int, default=5, help="Number of times to run the tax prep (5-10)")
    parser.add_argument("--model", type=str, default=None, help="Tax prep model override")
    args = parser.parse_args()
    
    runs = max(2, min(args.runs, 10))
    
    print("==================================================")
    # Explain in caveman what the script is doing to satisfy rule about explaining commands
    print("ME DO MULTI-RUN TAX PREP. ME CHOOSE BEST ONE.")
    print("==================================================")
    
    # 1. Verify/Setup directories
    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    # Check if tax data exists
    data_path = PROCESSED_DATA_DIR / "tax_data_2025.json"
    if not data_path.exists():
        print(f"Error: {data_path} not found. Please ensure you have run intake/extraction or generated tax data first.")
        return
        
    with open(data_path, "r", encoding="utf-8") as f:
        tax_data_str = f.read()
        tax_data = json.loads(tax_data_str)
        
    # Print the taxpayer names as soon as we know them!
    taxpayers = extract_names(tax_data)
    taxpayers_str = ", ".join(taxpayers) if taxpayers else "Unknown Taxpayer(s)"
    print(f"Filing for: {taxpayers_str}")
    print("==================================================")
        
    # Compute profile hash for zero-leakage logging
    profile_hash = "sha256:" + hashlib.sha256(tax_data_str.encode("utf-8")).hexdigest()
    
    # Load skills/rules
    skills_context = ""
    if SKILLS_DIR.exists():
        for skill_file in os.listdir(SKILLS_DIR):
            if skill_file.endswith(".md"):
                with open(SKILLS_DIR / skill_file, "r", encoding="utf-8") as sf:
                    skills_context += f"\n=== Skill: {skill_file} ===\n" + sf.read() + "\n"
                    
    current_date = datetime.date.today().isoformat()
    tax_year = tax_data.get("filing_details", {}).get("tax_year", 2025)

    system_prompt = build_system_prompt(tax_data, current_date, tax_year)
    system_prompt_short = "You are a tax preparation advisor. Generate a premium Tax Preparation Report & Action Plan by following the instructions, rules, and tax data provided in the user prompt."

    user_prompt = (
        f"{system_prompt}\n\n"
        f"--- TAX DATA ---\n{tax_data_str}\n\n"
        f"--- RULES & SKILLS CONTEXT ---\n{skills_context}"
    )
    
    # Resolve Model name
    target_model = args.model if args.model else TAX_PREP_MODEL
    model_name = resolve_model(target_model)
    print(f"Using Model: {model_name}")
    print(f"Generating {runs} candidates for review...")
    
    candidates = []
    scores = []
    issues_set = set()
    
    start_time = datetime.datetime.now()
    
    # Clear old candidates
    if CANDIDATES_DIR.exists():
        shutil.rmtree(CANDIDATES_DIR)
    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    
    for i in range(runs):
        # Linearly space temperature from 0.1 to 0.35 to get diversity
        temp = 0.1 + (i * (0.25 / max(1, runs - 1)))
        print(f"  Run {i+1}/{runs} (Temp: {temp:.2f})...", end="", flush=True)
        
        try:
            report = query_ollama(model_name, system_prompt_short, user_prompt, temp=temp)
            score, issues, matched_negs = score_report(report)
            
            # Save candidate file
            candidate_path = CANDIDATES_DIR / f"run_{i+1:02d}.md"
            with open(candidate_path, "w", encoding="utf-8") as f:
                f.write(report)
                
            candidates.append(report)
            scores.append(score)
            issues_set.update(issues)
            print(f" Done. Score: {score}/100")
            print(f"    - Passed Rubrics  : {', '.join(issues) if issues else 'None'}")
            if matched_negs:
                print(f"    - Matched Negatives (Penalty -5pts each): {', '.join(matched_negs)}")
        except Exception as e:
            print(f" Failed: {e}")
            scores.append(0)
            candidates.append(None)
            
    # Find best run
    best_score = -1
    best_idx = -1
    for idx, score in enumerate(scores):
        if score > best_score and candidates[idx] is not None:
            best_score = score
            best_idx = idx
            
    if best_idx == -1:
        print("\n[Error] All runs failed to generate reports.")
        return
        
    print(f"\nWinner: Run {best_idx+1} with score {best_score}/100")
    
    # Copy best report to tax_prep_report.md
    best_report = candidates[best_idx]
    model_type_str = f"Multi-run Best Candidate (Run {best_idx+1}/{runs}, Temp: {0.1 + (best_idx * (0.25 / max(1, runs - 1))):.2f}, Score: {best_score})"
    metadata_banner = f"> [!NOTE]\n> **Tax Prep Execution Engine**: {model_type_str} on {model_name}\n\n"
    
    report_path = FINAL_OUTPUTS_DIR / "tax_prep_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(metadata_banner + best_report)
        
    print(f"Promoted winner to {report_path.relative_to(WORKSPACE_DIR)}")
    
    # Stage 4: Form Generator
    print("\nGenerating PDF tax forms from data...")
    forms_generated = []
    try:
        import form_generator
        # Inject custom run info or mock execution info
        form_generator.main()
        
        # Check which forms were generated
        filled_dir = FINAL_OUTPUTS_DIR / "filled_forms"
        if filled_dir.exists():
            for f in os.listdir(filled_dir):
                if f.endswith(".pdf"):
                    forms_generated.append(f.replace(".pdf", ""))
    except Exception as e:
        print(f"  [Warning] Form generation failed: {e}")
        
    # Append sanitized entry to impact log
    elapsed = int((datetime.datetime.now() - start_time).total_seconds())
    
    log_entry = {
        "run_id": start_time.strftime("%Y%m%d%H%M%S"),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "profile_hash": profile_hash,
        "filing_status": tax_data.get("filing_details", {}).get("filing_status", "MFJ"),
        "tax_year": tax_year,
        "model_used": model_name,
        "num_candidates": runs,
        "scores": scores,
        "best_score": best_score,
        "best_run_index": best_idx + 1,
        "issues_flagged": list(issues_set),
        "potential_savings_found": "tax_minimization_planning" in issues_set,
        "forms_generated": forms_generated,
        "elapsed_seconds": elapsed
    }
    
    log_file = RUN_LOG_DIR / "impact_log.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")
        
    print(f"\nImpact metrics written to {log_file.relative_to(WORKSPACE_DIR)}")
    print(f"Filing run successfully completed in {elapsed} seconds!")

if __name__ == "__main__":
    main()
