import os
import json
import urllib.request
import urllib.error
import argparse
from pathlib import Path

# Configuration
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
TEST_MODEL = "tax-prep-gemma2"

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
    """
    Check if target_model is installed in Ollama.
    If not, find a suitable alternative or return the fallback.
    """
    installed = get_installed_models()
    if not installed:
        return target_model
        
    # Check exact match
    for m in installed:
        if m.lower() == target_model.lower():
            return m
            
    # Check case-insensitive and tagged variations
    target_clean = target_model.split(":")[0].lower()
    for m in installed:
        m_clean = m.split(":")[0].lower()
        if m_clean == target_clean:
            return m
            
    # Target model not found. Let's find any basic gemma model as fallback
    print(f"[Notice] Model '{target_model}' not found in local Ollama.")
    
    # Filter for gemma models, avoiding known medical/audit fine-tunes if possible
    gemma_models = []
    for m in installed:
        ml = m.lower()
        if "gemma" in ml and "medical" not in ml and "audit" not in ml:
            gemma_models.append(m)
            
    if gemma_models:
        gemma_models.sort(key=len)
        chosen = gemma_models[0]
        print(f"[Fallback] Found local Gemma model: '{chosen}'. Using it.")
        return chosen
        
    # If no basic gemma, try any model containing gemma
    any_gemma = [m for m in installed if "gemma" in m.lower()]
    if any_gemma:
        print(f"[Fallback] Found local model containing Gemma: '{any_gemma[0]}'. Using it.")
        return any_gemma[0]
        
    # No gemma models found, fall back to default_fallback
    print(f"[Warning] No local Gemma models detected. Defaulting to '{default_fallback}'.")
    return default_fallback

# Test suite containing scenarios and key verification terms (eval criteria)
TEST_SUITE = [
    {
        "id": "T1_PASSIVE_LOSS",
        "description": "High-income passive rental loss phase-out test",
        "prompt": "Taxpayer has W-2 income of $480,000 and claims a $5,000 loss on an active rental property in Michigan. Can they deduct this loss?",
        "required_keywords": ["phase-out", "suspended", "Form 8582"],
        "negative_keywords": ["deduct in full", "allowable deduction"]
    },
    {
        "id": "T2_MACRS_DEPR",
        "description": "Residential rental MACRS depreciation parameters test",
        "prompt": "What MACRS depreciation rules and recovery period apply to a residential rental property?",
        "required_keywords": ["27.5", "straight-line", "mid-month", "land"],
        "negative_keywords": ["39 years", "15 years", "double declining"]
    },
    {
        "id": "T3_HOBBY_LOSS",
        "description": "Sole Proprietorship with persistent losses (Hobby classification)",
        "prompt": "A taxpayer has a side business that reported losses for 5 consecutive years. Under TCJA, can they deduct expenses?",
        "required_keywords": ["hobby", "non-deductible", "Schedule 1", "183"],
        "negative_keywords": ["Schedule C deduction", "deduct business expense"]
    },
    {
        "id": "T4_SAFE_HARBOR",
        "description": "High-income safe harbor estimated tax payments",
        "prompt": "The taxpayer had an AGI of $480,000 last year. What percentage of last year's tax liability do they need to pay to meet the safe harbor rule?",
        "required_keywords": ["110%", "safe harbor"],
        "negative_keywords": ["90%", "100%"]
    },
    {
        "id": "T5_EXTENSION_LATE_PAY",
        "description": "Form 4868 late payment vs late filing rules",
        "prompt": "If a taxpayer files Form 4868 for an extension on April 15 but pays the remaining tax in October, do they face any penalties?",
        "required_keywords": ["failure-to-pay", "interest", "0.5%"],
        "negative_keywords": ["failure-to-file penalty", "5% per month"]
    }
]

def query_model(prompt: str, model_name: str) -> str:
    """Helper to query the local Ollama instance."""
    url = f"{OLLAMA_HOST}/api/chat"
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "You are a tax preparation advisor. Evaluate the scenario strictly according to IRC rules and IRS publications."},
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "options": {
            "temperature": 0.0  # Zero temperature for deterministic evaluation
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

def run_evaluation(model_name: str):
    print("==================================================")
    print(f"Evaluating Model Accuracy for: {model_name}")
    print("==================================================")
    
    passed_tests = 0
    total_tests = len(TEST_SUITE)
    
    for i, test in enumerate(TEST_SUITE, 1):
        print(f"\n[{i}/{total_tests}] Running: {test['description']} ({test['id']})")
        print(f"Prompt: {test['prompt']}")
        
        try:
            response = query_model(test['prompt'], model_name)
            response_lower = response.lower()
            
            # Evaluate keywords
            missed_keywords = []
            for kw in test['required_keywords']:
                if kw.lower() not in response_lower:
                    missed_keywords.append(kw)
                    
            found_negatives = []
            for kw in test['negative_keywords']:
                if kw.lower() in response_lower:
                    found_negatives.append(kw)
            
            # Print grading results
            if not missed_keywords and not found_negatives:
                print("Result: [PASS]")
                passed_tests += 1
            else:
                print("Result: [FAIL]")
                if missed_keywords:
                    print(f"  - Missed required keywords: {missed_keywords}")
                if found_negatives:
                    print(f"  - Contained forbidden words: {found_negatives}")
                    
            print("-" * 50)
            print("Model Response Preview:")
            # Print first 2-3 lines of response
            preview = "\n".join(response.split("\n")[:4])
            print(f"{preview}\n...")
            print("=" * 50)
            
        except urllib.error.URLError as e:
            print(f"Connection Error: Could not connect to Ollama. Make sure it is running and model '{model_name}' is loaded.")
            print(e)
            return
        except Exception as e:
            print(f"Unexpected Error during test run: {e}")
            
    accuracy = (passed_tests / total_tests) * 100
    print(f"\nEvaluation Summary:")
    print(f"  Total Scenarios Tested: {total_tests}")
    print(f"  Passed Scenarios: {passed_tests}")
    print(f"  Accuracy Score: {accuracy:.2f}%")
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate Local Ollama Model Accuracy")
    parser.add_argument("--model", type=str, default="tax-prep-gemma2", help="Ollama model name to evaluate")
    args = parser.parse_args()
    
    # Resolve the model name
    print("Checking Ollama configuration...")
    resolved_model_name = resolve_model(args.model, default_fallback="gemma2:9b")
    
    run_evaluation(resolved_model_name)
