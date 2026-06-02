# /// script
# dependencies = [
#   "pypdf",
#   "cryptography",
#   "pymupdf",
#   "pdf2image",
# ]
# ///

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

# Fix Windows cp1252 console encoding for LLM output containing emoji/unicode
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from agents.intake import run_intake
from agents.planner import run_planner
from agents.extractor import run_extractor
from agents.strategist import run_strategist
from agents.form_proxy import run_form_proxy
from agents.qa_reviewer import run_qa
from agents.savings import run_savings
from agents.comms import run_comms
import form_generator

WORKSPACE_DIR = Path(__file__).parent.resolve()
PROCESSED_DATA_DIR = WORKSPACE_DIR / "processed_data"
FINAL_OUTPUTS_DIR = WORKSPACE_DIR / "final_outputs"
SKILLS_DIR = WORKSPACE_DIR / ".agents" / "skills"

def initialize_state(docs_dir: Path) -> dict:
    state_file = PROCESSED_DATA_DIR / "state.json"
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
            return state
        except Exception as e:
            print(f"Warning: Could not read existing state.json, starting fresh. Error: {e}")
            
    return {
        "meta": {
            "tax_year": 2025,
            "loop_iteration": 0,
            "status": "starting",
            "last_agent": "none",
            "timestamp": datetime.now().isoformat()
        },
        "manifest": {},
        "taxpayer": {},
        "extracted": {},
        "prior_year": {},
        "strategies": {},
        "proxy_forms": {},
        "qa_issues": [],
        "savings_opportunities": [],
        "comms": {}
    }

def save_state(state: dict):
    PROCESSED_DATA_DIR.mkdir(exist_ok=True)
    state_file = PROCESSED_DATA_DIR / "state.json"
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def generate_final_pdfs(state: dict):
    print("Generating final PDFs...")
    try:
        form_generator.main()
    except Exception as e:
        print(f"Error generating PDFs: {e}")

def run_tax_loop(docs_dir: Path, models: dict):
    state = initialize_state(docs_dir)
    
    taxpayer_file = docs_dir / "taxpayer_info.json"
    if taxpayer_file.exists():
        try:
            with open(taxpayer_file, "r", encoding="utf-8") as f:
                state["taxpayer"] = json.load(f)
                state["prior_year"] = state["taxpayer"].get("filing_details", {})
        except Exception as e:
            print(f"Warning: Could not read taxpayer_info.json: {e}")
            
    while True:
        state["meta"]["loop_iteration"] += 1
        state["meta"]["timestamp"] = datetime.now().isoformat()
        print(f"\\n==================================================")
        print(f"Tax CPA-Loop - Iteration {state['meta']['loop_iteration']}")
        print(f"==================================================")
        
        run_intake(state, docs_dir, model=models["sorter"])
        run_planner(state, model=models["reader"])
        run_extractor(state, docs_dir, model=models["reader"])
        
        try:
            tax_data_file = PROCESSED_DATA_DIR / "tax_data_2025.json"
            with open(tax_data_file, "w", encoding="utf-8") as f:
                json.dump(state.get("extracted", {}), f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save tax_data_2025.json: {e}")

        # ── Bouncer: build PII-free bundle for cloud hand-off ──────────────
        try:
            from shared.cloud_bundle import build_bundle, CloudBundleError
            bundle_path = build_bundle(state)
            state["meta"]["sanitized_bundle_path"] = str(bundle_path)
        except CloudBundleError as e:
            print(f"\n[BOUNCER FAIL] {e}")
            print("Pipeline halted. Fix redaction issues before continuing.")
            raise
        except Exception as e:
            print(f"[Bouncer] Warning: bundle build skipped ({e})")
        # ────────────────────────────────────────────────────────────────────

        run_strategist(state, SKILLS_DIR, model=models["auditor"])
        run_form_proxy(state)
        run_qa(state, model=models["auditor"])
        run_savings(state, model=models["auditor"])
        run_comms(state, FINAL_OUTPUTS_DIR, model=models["reader"])
        
        save_state(state)
        
        if state["comms"].get("ready_to_file"):
            print("\\n✅ Ready to file! Generating final PDF forms...")
            generate_final_pdfs(state)
            break
        else:
            status = state["comms"].get("status_report", "No report generated.")
            # Sanitize for Windows console encoding
            safe_status = status.encode('ascii', errors='replace').decode('ascii')
            print(f"\\n--- STATUS REPORT ---\\n{safe_status}")
            print("\\nWaiting for user to provide missing docs/answers...")
            input("Press Enter after updating docs directory...")

def main(args_list=None):
    parser = argparse.ArgumentParser(description="Local Multi-Agent Tax Swarm Orchestration Engine")
    parser.add_argument("--docs-dir", type=str, default=None, help="Path to directory containing raw tax documents")
    parser.add_argument("--model", type=str, default="gemma4:latest", help="Set the default Gemma model to use for all agents")
    parser.add_argument("--sorter-model", type=str, default=None, help="Model override for Intake Agent")
    parser.add_argument("--reader-model", type=str, default=None, help="Model override for Extraction Agent")
    parser.add_argument("--audit-model", type=str, default="gemma4:latest", help="Model override for Tax Prep Agent (default: gemma4:latest)")
    args = parser.parse_args(args_list)
    
    raw_docs_dir = Path(args.docs_dir) if args.docs_dir else Path(os.environ.get("TAX_DOCS_DIR", str(WORKSPACE_DIR / "raw_docs")))
    
    from shared.ollama_client import resolve_model
    models = {
        "sorter": resolve_model(args.sorter_model or args.model),
        "reader": resolve_model(args.reader_model or args.model),
        "auditor": resolve_model(args.audit_model or args.model)
    }
    
    # Let agents/shared/ollama_client resolve models natively if we want, but simple pass-through is enough for the slim controller
    
    raw_docs_dir.mkdir(parents=True, exist_ok=True)
    FINAL_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    
    run_tax_loop(raw_docs_dir, models)

if __name__ == "__main__":
    main()
