import os
import json
import urllib.request
import urllib.error
import re

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
_SSN_RE = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')

def _assert_local_host(url: str) -> None:
    """Hard-abort if the Ollama URL is not localhost. Tax data must never leave this machine."""
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    if host not in ("localhost", "127.0.0.1", "::1"):
        raise RuntimeError(
            f"[PRIVACY VIOLATION] Refusing to send tax data to external host: {url}\n"
            "Only a local Ollama instance is permitted. "
            "Set OLLAMA_HOST=http://localhost:11434"
        )

def scrub_ssns(obj):
    """Recursively remove SSN patterns from any JSON-serializable object before saving."""
    if isinstance(obj, str):
        return _SSN_RE.sub('[REDACTED]', obj)
    if isinstance(obj, dict):
        return {k: scrub_ssns(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_ssns(item) for item in obj]
    return obj

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
        
    for m in installed:
        if m.lower() == target_model.lower():
            return m
            
    target_clean = target_model.split(":")[0].lower()
    for m in installed:
        m_clean = m.split(":")[0].lower()
        if m_clean == target_clean:
            return m
            
    print(f"[Notice] Model '{target_model}' not found in local Ollama.")
    
    gemma_models = []
    for m in installed:
        ml = m.lower()
        if "gemma" in ml and "medical" not in ml and "audit" not in ml:
            gemma_models.append(m)
            
    if gemma_models:
        def gemma_sort_key(name):
            nl = name.lower()
            if "gemma4" in nl: return (0, len(name))
            if "gemma3" in nl: return (1, len(name))
            if "gemma2" in nl: return (2, len(name))
            return (3, len(name))
        gemma_models.sort(key=gemma_sort_key)
        chosen = gemma_models[0]
        print(f"[Fallback] Found local Gemma model: '{chosen}'. Using it.")
        return chosen
        
    any_gemma = [m for m in installed if "gemma" in m.lower()]
    if any_gemma:
        print(f"[Fallback] Found local model containing Gemma: '{any_gemma[0]}'. Using it.")
        return any_gemma[0]
        
    print(f"[Warning] No local Gemma models detected. Defaulting to '{default_fallback}'.")
    return default_fallback

def query_ollama(model: str, system_prompt: str, user_prompt: str, json_format: bool = False, num_ctx: int = 8192, images: list = None, temperature: float = 0.8) -> str:
    """Query local Ollama only. PRIVACY: Hard-errors if host is not localhost."""
    url = f"{OLLAMA_HOST}/api/chat"
    _assert_local_host(url)
    print(f"  [PRIVACY] Local Gemma only — {model} @ {OLLAMA_HOST}")
    user_message = {"role": "user", "content": user_prompt}
    if images:
        user_message["images"] = images
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            user_message
        ],
        "stream": False,
        "options": {
            "num_ctx": num_ctx,
            "temperature": temperature
        }
    }
    if json_format:
        payload["format"] = "json"
        
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
