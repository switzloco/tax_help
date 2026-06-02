import os
import json
from pathlib import Path
from shared.ollama_client import query_ollama
from shared.tax_math import calculate_late_penalties_and_interest, safe_float

def run_strategist(state: dict, skills_dir: Path, model: str = "gemma4:26b") -> None:
    print("\\n--- [Agent 4] Strategist Agent ---")
    extracted = state.get("extracted", {})
    prior_year = state.get("plan", {}).get("prior_year_baseline", {})
    
    # Load all agent skills
    skills_context = ""
    if skills_dir.exists():
        for skill_file in os.listdir(skills_dir):
            if skill_file.endswith(".md"):
                with open(skills_dir / skill_file, "r", encoding="utf-8") as sf:
                    skills_context += f"\\n=== Skill: {skill_file} ===\\n" + sf.read() + "\\n"
                    
    # Only send summary data to LLM, not raw extracted data
    summary_data = {
        "w2_summary": extracted.get("w2_summary"),
        "rental_property": extracted.get("rental_property"),
        "side_business": extracted.get("side_business"),
        "prior_year_baseline": prior_year
    }
    
    system_prompt = (
        "You are the Tax Strategist Agent.\\n"
        "Evaluate the provided tax data against IRS rules and return a JSON strategy analysis.\\n"
        "Output ONLY JSON with keys: safe_harbor, passive_loss, hobby_loss, penalties, recommendations.\\n"
        "No markdown blocks."
    )
    
    user_prompt = (
        f"Tax Data Summary:\\n{json.dumps(summary_data, indent=2)}\\n\\n"
        f"Rules Context:\\n{skills_context}\\n\\n"
        "Provide your analysis in the required JSON format."
    )
    
    response_str = query_ollama(model, system_prompt, user_prompt, json_format=True)
    
    try:
        strategies = json.loads(response_str)
        state["strategies"] = strategies
    except Exception as e:
        print(f"  [Warning] Strategist failed to generate valid JSON: {e}")
        state["strategies"] = {
            "safe_harbor": {"met": False},
            "passive_loss": {"treatment": "suspended"},
            "hobby_loss": {"risk_level": "unknown"},
            "penalties": {"late_payment": 0, "interest": 0, "total_balance_due": 0},
            "recommendations": []
        }
        
    state["meta"]["last_agent"] = "strategist"
