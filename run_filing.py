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
    """Score candidate report against a strict compliance rubric and track negatives."""
    text_lower = text.lower()
    score = 0
    passed_rubrics = []
    matched_negatives = []
    
    # Rubric 1: Safe Harbor (10 pts)
    sh_keywords = ["110%", "safe harbor", "107,800"]
    if any(k in text_lower for k in sh_keywords):
        score += 10
        passed_rubrics.append("safe_harbor_evaluation")
        
    # Rubric 2: Late Payment Penalty (10 pts)
    ftp_keywords = ["failure-to-pay", "failure to pay", "penalty", "240"]
    if any(k in text_lower for k in ftp_keywords):
        score += 10
        passed_rubrics.append("late_payment_penalty")
        
    # Rubric 3: Interest (10 pts)
    interest_keywords = ["interest", "322", "8%"]
    if any(k in text_lower for k in interest_keywords):
        score += 10
        passed_rubrics.append("interest_calculation")
        
    # Rubric 4: Passive Loss Suspension (15 pts)
    pl_keywords = ["phase-out", "phase out", "suspended", "suspension", "8582", "4,182"]
    if any(k in text_lower for k in pl_keywords):
        score += 15
        passed_rubrics.append("passive_loss_suspension")
        
    # Rubric 5: MACRS (15 pts)
    macrs_keywords = ["27.5", "straight-line", "mid-month", "land", "70,000"]
    if any(k in text_lower for k in macrs_keywords):
        score += 15
        passed_rubrics.append("macrs_depreciation")
        
    # Rubric 6: Hobby Loss (15 pts)
    hobby_keywords = ["hobby", "183", "non-deductible", "not deductible", "disallowed"]
    if any(k in text_lower for k in hobby_keywords):
        score += 15
        passed_rubrics.append("hobby_loss_risk")
        
    # Rubric 7: Minimization Strategies (10 pts)
    savings_keywords = ["1,515.98", "4,350", "savings", "loophole"]
    if any(k in text_lower for k in savings_keywords):
        score += 10
        passed_rubrics.append("tax_minimization_planning")
        
    # Rubric 8: Missing Documents & Client Questions (15 pts)
    missing_docs_keywords = ["missing", "requested documents", "questions", "receipt"]
    if any(k in text_lower for k in missing_docs_keywords):
        score += 15
        passed_rubrics.append("missing_documents_and_questions")
        
    # Penalties for forbidden/negative keywords (subtract 5 pts each)
    negatives = ["deduct in full", "allowable deduction", "failure-to-file penalty", "5% per month"]
    for neg in negatives:
        if neg in text_lower:
            score -= 5
            matched_negatives.append(neg)
            
    # Cap score between 0 and 100
    score = max(0, min(score, 100))
    return score, passed_rubrics, matched_negatives

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
    tax_year = 2025
    
    system_prompt = (
        "You are the Tax Prep Agent (Advisor). Your goal is to review the compiled tax data against the provided skills rules and generate a premium, high-impact Tax Preparation Report & Action Plan.\n"
        f"CRITICAL CONSTANTS:\n"
        f"- Current Date of Review: {current_date} (Use EXACTLY this date at the top of your report! Never use 2023 or any other year)\n"
        f"- Tax Year Under Review: {tax_year}\n\n"
        "REQUIRED REPORT STRUCTURE & CONTENT:\n"
        "Your report must be written in professional markdown with clear headings, tables, and alerts (e.g. > [!NOTE], > [!IMPORTANT]). Tone should be constructive and advisory (\"here's how we do this right, here are next steps\"), NOT adversarial or punitive. Address the following sections in detail:\n\n"
        "1. EXECUTIVE SUMMARY:\n"
        f"   - Highlight that the review date is {current_date} and the tax year under review is {tax_year}.\n"
        "   - Summarize the key recommendations: rental passive loss treatment, MACRS depreciation, side-business structuring, and resolving remaining liabilities.\n\n"
        "2. ESTIMATED TAX & SAFE HARBOR EVALUATION:\n"
        "   - Analyze safe harbor compliance: Prior year tax liability was $98,000. For high-income taxpayers (AGI > $150,000), the safe harbor is 110% of prior year tax, which equals $107,800.\n"
        "   - Since the taxpayer had $115,000 in federal withholding, they exceeded the 110% safe harbor threshold of $107,800 and are exempt from the underpayment penalty (Form 2210).\n\n"
        "3. LATE PAYMENT PENALTIES & INTEREST CALCULATIONS (AS OF OCTOBER 14, 2026):\n"
        "   - Detail the remaining tax due of $8,000 as of the April 15, 2026 deadline.\n"
        "   - Calculate the Late Payment Penalty (IRC § 6651(a)(2)): 0.5% per month or fraction of a month from April 15, 2026 to October 14, 2026. This is exactly 6 months, resulting in a 3.0% penalty ($240.00).\n"
        "   - Calculate the Late Payment Interest (IRC § 6621): Interest compounds daily on the unpaid tax from April 15, 2026 to October 14, 2026. Using an 8.0% annual rate, the interest is approximately $322.00.\n"
        "   - Present a prominent 'Tax Liability and Penalty Calculation' table showing:\n"
        "     * Remaining Tax Principal Due: $8,000.00\n"
        "     * Failure-to-Pay Penalty (3.0%): $240.00\n"
        "     * Estimated Interest (8% compounded daily): $322.00\n"
        "     * Total Balance Due: $8,562.00\n\n"
        "4. COMPLIANCE REVIEW & RECOMMENDED ACTIONS:\n"
        "   - Rental Passive Loss Suspension (IRC § 469): Verify that the $25,000 special allowance is 100% phased out due to high MAGI ($480,000 W-2 income). Explain that the rental loss of $4,182 must be suspended and carried forward on Form 8582, unless an optimization loophole is utilized.\n"
        "   - MACRS Depreciation: Confirm that the residential rental property must be depreciated over 27.5 years using straight-line and mid-month convention, and that land value ($70,000) was correctly excluded from the depreciable basis ($280,000).\n"
        "   - Hobby Loss Presumption (IRC § 183): Note that this side business has reported losses in 4 out of 5 years, which may trigger hobby loss classification. Recommended action: establish profit motive documentation (see next steps) to protect business status and continue deducting valid business expenses under the TCJA.\n\n"
        "5. TAX MINIMIZATION STRATEGIES (LEGAL LOOPHOLES & PLANNING):\n"
        "   Propose aggressive yet legal planning strategies to minimize taxes and penalties, calculating the exact potential savings based on a combined 36.25% marginal tax rate (32% Federal + 4.25% Michigan state):\n"
        "   - Short-Term Rental (STR) Loophole (Treas. Reg. § 1.469-1T(e)(3)(ii)(A)): Restructure the property to average stays of <= 7 days and meet material participation (>100 hours and more than others). This bypasses rental passive limits, allowing the $4,182 rental loss to be fully deducted against W-2 income. **Potential Tax Savings: $1,515.98**.\n"
        "   - Real Estate Professional Status (REPS) Spouse Strategy (IRC § 469(c)(7)): If Spouse 2 qualifies by performing >750 hours and >50% of services in real property business, all rental losses become fully deductible against W-2 income.\n"
        "   - Hobby-to-Business Restructuring: Outline a plan to establish profit motive under the 9 IRS factors (separate business bank account, formal business plan, consulting CPAs, dedicating time). This allows them to deduct the $7,000 Schedule C net loss instead of paying tax on the $5,000 gross revenue with zero deductions. **Potential Tax Savings: $4,350.00** (reclaims $2,537.50 from the loss and avoids $1,812.50 tax on gross revenue).\n\n"
        "6. NEXT STEPS & ACTION ITEMS:\n"
        "   Provide a clear, actionable checklist of next steps for the taxpayer, including:\n"
        "   - Documenting the profit motive for the side business (Schedule C) to support business status.\n"
        "   - Reviewing material participation hours (average stays <= 7 days) if electing the STR loophole.\n"
        "   - Tracking hours for REPS if applicable.\n"
        "   - Setting up separate business bank accounts and keeping detailed logs.\n"
        "   - Resolving the remaining tax balance and preparing/submitting the filled tax forms.\n\n"
        "Write your report in clear, formal, and advisory language. Do not output raw JSON, only markdown."
    )
    
    system_prompt_short = "You are a tax preparation advisor. Generate a premium, high-impact Tax Preparation Report & Action Plan by following the detailed instructions, rules, and tax data provided in the user prompt."
    
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
