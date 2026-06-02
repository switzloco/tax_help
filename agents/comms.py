import json
from pathlib import Path
from shared.ollama_client import query_ollama

def run_comms(state: dict, output_dir: Path, model: str = "gemma4:latest") -> None:
    print("\\n--- [Agent 7] Comms Agent ---")
    manifest = state.get("manifest", {})
    plan = state.get("plan", {})
    qa_issues = state.get("qa_issues", [])
    savings = state.get("savings_opportunities", [])
    
    error_issues = [i for i in qa_issues if i.get("severity") == "error"]
    gaps = plan.get("gaps_identified", [])
    
    ready_to_file = len(error_issues) == 0 and len(gaps) == 0
    state["comms"] = {"ready_to_file": ready_to_file}
    
    system_prompt = (
        "You are the Tax Communications Agent.\\n"
        "Synthesize the state into a clear human-readable markdown status report.\\n"
        "Include sections: Filing Readiness, Missing Documents, and Questions for You.\\n"
        "DO NOT output JSON. Output purely formatted markdown."
    )
    
    user_prompt = (
        f"Manifest Summary:\\n{json.dumps(manifest.get('doc_type_summary'), indent=2)}\\n"
        f"QA Issues:\\n{json.dumps(qa_issues, indent=2)}\\n"
        f"Gaps:\\n{json.dumps(gaps, indent=2)}\\n"
        f"Savings Opportunities:\\n{json.dumps(savings, indent=2)}\\n"
        f"Ready to file: {ready_to_file}"
    )
    
    report = query_ollama(model, system_prompt, user_prompt)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "status_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
        
    print(f"  -> Generated status report at {report_path.name}")
    state["comms"]["status_report"] = report
    state["meta"]["last_agent"] = "comms"
