import json
from shared.ollama_client import query_ollama

def run_planner(state: dict, model: str = "gemma4:latest") -> None:
    print("\\n--- [Agent 2] Planner Agent ---")
    manifest = state.get("manifest", {})
    prior_year = state.get("prior_year", {})
    taxpayer = state.get("taxpayer", {})
    
    system_prompt = (
        "You are a Tax Planner Agent.\\n"
        "Review the prior year baseline and current year manifest.\\n"
        "Generate a structured JSON document plan identifying missing documents and an extraction queue.\\n"
        "Output ONLY JSON. No markdown blocks."
    )
    
    user_prompt = (
        f"Manifest:\\n{json.dumps(manifest, indent=2)}\\n"
        f"Prior Year Baseline:\\n{json.dumps(prior_year, indent=2)}\\n"
        f"Taxpayer Profile:\\n{json.dumps(taxpayer, indent=2)}\\n\\n"
        "Create a plan with 'expected_documents' (list), 'extraction_queue' (list of files and data to extract), "
        "'schedules_to_prepare' (list), and 'gaps_identified' (list of strings)."
    )
    
    response_str = query_ollama(model, system_prompt, user_prompt, json_format=True)
    
    try:
        plan = json.loads(response_str)
        state["plan"] = plan
    except Exception as e:
        print(f"  [Warning] Planner Agent failed to generate valid JSON: {e}")
        # Fallback simplistic plan
        state["plan"] = {
            "expected_documents": [],
            "extraction_queue": [{"file": doc["file"], "type": doc["type"]} for doc in manifest.get("documents", []) if doc.get("type") != "UNKNOWN"],
            "schedules_to_prepare": ["1040"],
            "gaps_identified": ["Failed to generate complex plan, using fallback."]
        }
        
    state["meta"]["last_agent"] = "planner"
