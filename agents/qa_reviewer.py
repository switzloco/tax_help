import json
from shared.ollama_client import query_ollama

def run_qa(state: dict, model: str = "gemma4:26b") -> None:
    print("\\n--- [Agent 6] QA Agent ---")
    proxy_forms = state.get("proxy_forms", {})
    
    # 1. Programmatic checks
    issues = []
    f1040 = proxy_forms.get("f1040", {})
    if f1040.get("wages", 0) > 0 and f1040.get("federal_withholding", 0) == 0:
        issues.append({"severity": "error", "field": "f1040.federal_withholding", "message": "Wages exist but no federal withholding."})
    
    if proxy_forms.get("schedule_c") and proxy_forms["schedule_c"].get("gross_receipts", 0) == 0:
        issues.append({"severity": "warning", "field": "schedule_c.gross_receipts", "message": "Schedule C generated but no gross receipts found."})
        
    # 2. LLM Sniff test
    system_prompt = (
        "You are a Tax QA Reviewer.\\n"
        "Review the provided computed proxy tax forms for any red flags.\\n"
        "Output ONLY JSON in the format: {'qa_issues': [{'severity': 'error/warning/info', 'field': 'string', 'message': 'string'}]}"
    )
    
    user_prompt = f"Proxy Forms Data:\\n{json.dumps(proxy_forms, indent=2)}\\nAny red flags?"
    
    response_str = query_ollama(model, system_prompt, user_prompt, json_format=True)
    try:
        llm_issues = json.loads(response_str).get("qa_issues", [])
        issues.extend(llm_issues)
    except Exception as e:
        print(f"  [Warning] QA Agent failed to parse LLM response: {e}")
        
    state["qa_issues"] = issues
    state["meta"]["last_agent"] = "qa_reviewer"
