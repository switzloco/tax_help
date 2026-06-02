import json
from shared.ollama_client import query_ollama

def run_savings(state: dict, model: str = "gemma4:26b") -> None:
    print("\\n--- [Agent 6b] Savings Agent ---")
    extracted = state.get("extracted", {})
    strategies = state.get("strategies", {})
    proxy_forms = state.get("proxy_forms", {})
    
    system_prompt = (
        "You are the Tax Savings Agent.\\n"
        "Review the strategies and proxy forms to identify optimization opportunities.\\n"
        "Output ONLY JSON in the format: {'savings_opportunities': [{'description': 'string', 'potential_savings': float, 'action_required': 'string'}]}"
    )
    
    user_prompt = (
        f"Strategies:\\n{json.dumps(strategies, indent=2)}\\n"
        f"Proxy Forms:\\n{json.dumps(proxy_forms, indent=2)}\\n"
        "Identify savings opportunities."
    )
    
    response_str = query_ollama(model, system_prompt, user_prompt, json_format=True)
    try:
        opportunities = json.loads(response_str).get("savings_opportunities", [])
        state["savings_opportunities"] = opportunities
    except Exception as e:
        print(f"  [Warning] Savings Agent failed to parse LLM response: {e}")
        state["savings_opportunities"] = []
        
    state["meta"]["last_agent"] = "savings"
