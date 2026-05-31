# /// script
# dependencies = [
#   "fastapi",
#   "uvicorn",
#   "python-multipart",
#   "pypdf",
#   "cryptography",
#   "pymupdf",
#   "pdf2image",
# ]
# ///

import os
import json
import re
import shutil
import sys
import asyncio
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ============================================================
# PRIVACY FIREWALL
# Tax data is ONLY ever sent to local Ollama (localhost:11434).
# No cloud APIs (Gemini, Claude, OpenAI, etc.) receive any data.
# ============================================================

def _assert_local_host(url: str) -> None:
    """Hard-abort if the Ollama URL is not localhost. Tax data must never leave this machine."""
    host = urlparse(url).hostname or ""
    if host not in ("localhost", "127.0.0.1", "::1"):
        raise RuntimeError(
            f"[PRIVACY VIOLATION] Refusing to send tax data to external host: {url}\n"
            "Only a local Ollama instance is permitted."
        )

class ConfigPayload(BaseModel):
    docs_dir: str

class RunPayload(BaseModel):
    mode: str = "standard"
    runs: int = 5

app = FastAPI(title="Local Tax Swarm Web Dashboard")

# Paths
WORKSPACE_DIR = Path(__file__).parent.resolve()
RAW_DOCS_DIR = Path(os.environ.get("TAX_DOCS_DIR", r"C:\Users\nswitzer\Antigrav Proj\Tax Docs"))
PROCESSED_DATA_DIR = WORKSPACE_DIR / "processed_data"
FINAL_OUTPUTS_DIR = WORKSPACE_DIR / "final_outputs"
FILLED_FORMS_DIR = FINAL_OUTPUTS_DIR / "filled_forms"
TAX_PREP_REPORT_PATH = FINAL_OUTPUTS_DIR / "tax_prep_report.md"
TAX_DATA_PATH = PROCESSED_DATA_DIR / "tax_data_2025.json"

# Ensure directories exist
RAW_DOCS_DIR.mkdir(exist_ok=True)
PROCESSED_DATA_DIR.mkdir(exist_ok=True)
FINAL_OUTPUTS_DIR.mkdir(exist_ok=True)
FILLED_FORMS_DIR.mkdir(exist_ok=True)

# Global Swarm Execution State
class SwarmState:
    running = False
    logs = []
    process = None

state = SwarmState()
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Validate OLLAMA_HOST is local on startup
try:
    _assert_local_host(OLLAMA_HOST)
    print(f"[PRIVACY] Tax data routes ONLY to local Gemma (Ollama @ {OLLAMA_HOST}). No cloud APIs are called.")
except RuntimeError as _e:
    print(f"[STARTUP ERROR] {_e}")
    sys.exit(1)

# Model Resolution Helper (same as orchestrator.py)
def get_installed_models() -> list:
    url = f"{OLLAMA_HOST}/api/tags"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3.0) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return [m["name"] for m in res_data.get("models", [])]
    except Exception:
        return []

def resolve_gemma_model() -> str:
    installed = get_installed_models()
    if not installed:
        return "gemma4:latest"
    
    # Prioritize Gemma 4 models first
    for m in installed:
        ml = m.lower()
        if "gemma4" in ml and "medical" not in ml and "audit" not in ml:
            return m

    # Then Gemma 3
    for m in installed:
        ml = m.lower()
        if "gemma3" in ml and "medical" not in ml and "audit" not in ml:
            return m
            
    # Then Gemma 2
    for m in installed:
        ml = m.lower()
        if "gemma2" in ml and "medical" not in ml and "audit" not in ml:
            return m
            
    # Any other Gemma
    for m in installed:
        if "gemma" in m.lower():
            return m
            
    # Default to first installed model or fallback
    return installed[0]

# --- API ENDPOINTS ---

@app.get("/api/status")
def get_status():
    raw_files = [f for f in os.listdir(RAW_DOCS_DIR) if f != ".gitkeep"]
    filled_forms = [f for f in os.listdir(FILLED_FORMS_DIR) if f.endswith(".pdf")]
    
    report_exists = TAX_PREP_REPORT_PATH.exists()
    data_exists = TAX_DATA_PATH.exists()
    
    return {
        "running": state.running,
        "raw_files": raw_files,
        "filled_forms": filled_forms,
        "report_exists": report_exists,
        "data_exists": data_exists,
        "docs_dir": str(RAW_DOCS_DIR)
    }

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    # Block forbidden paths or files (just general safety check)
    filename = file.filename
    if any(forbidden in filename for forbidden in ["OneDrive", "Stryker"]):
        raise HTTPException(status_code=400, detail="Invalid file name or path.")
        
    destination = RAW_DOCS_DIR / filename
    try:
        with open(destination, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"filename": filename, "status": "uploaded"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

@app.post("/api/config")
def update_config(payload: ConfigPayload):
    global RAW_DOCS_DIR
    path_str = payload.docs_dir.strip()
    if not path_str:
        raise HTTPException(status_code=400, detail="Path cannot be empty.")
    
    # Enforce security boundaries and strict directory lock
    path = Path(path_str).resolve()
    allowed_root = Path(r"C:\Users\nswitzer\Antigrav Proj").resolve()
    try:
        path.relative_to(allowed_root)
    except ValueError:
        raise HTTPException(
            status_code=400, 
            detail="Access denied. Path must be inside C:\\Users\\nswitzer\\Antigrav Proj"
        )
        
    if any(forbidden in path_str for forbidden in ["OneDrive", "Stryker"]):
        raise HTTPException(status_code=400, detail="Access denied. Path contains restricted folder names.")
        
    try:
        path.mkdir(parents=True, exist_ok=True)
        RAW_DOCS_DIR = path
        return {"status": "success", "docs_dir": str(RAW_DOCS_DIR)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to access/create directory: {str(e)}")

@app.post("/api/delete-file")
def delete_file(payload: dict):
    filename = payload.get("filename")
    if not filename:
        raise HTTPException(status_code=400, detail="Filename required")
        
    filepath = RAW_DOCS_DIR / filename
    if filepath.exists() and filepath.parent == RAW_DOCS_DIR:
        os.remove(filepath)
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="File not found")

@app.post("/api/clear-all")
def clear_all():
    # Clear raw docs (except .gitkeep)
    for item in os.listdir(RAW_DOCS_DIR):
        if item != ".gitkeep":
            p = RAW_DOCS_DIR / item
            if p.is_file():
                os.remove(p)
            elif p.is_dir():
                shutil.rmtree(p)
                
    # Clear processed data
    for item in os.listdir(PROCESSED_DATA_DIR):
        p = PROCESSED_DATA_DIR / item
        if p.is_file():
            os.remove(p)
            
    # Clear filled forms
    for item in os.listdir(FILLED_FORMS_DIR):
        p = FILLED_FORMS_DIR / item
        if p.is_file():
            os.remove(p)
            
    # Delete report
    if TAX_PREP_REPORT_PATH.exists():
        os.remove(TAX_PREP_REPORT_PATH)
        
    state.logs = ["Workspace cleared."]
    return {"status": "cleared"}

def run_orchestrator_sync(mode: str = "standard", runs: int = 5):
    import subprocess
    state.running = True
    state.logs = ["[System] Starting Tax Swarm Orchestration...\n"]
    
    # Locate UV binary
    uv_binary = r"C:\Users\nswitzer\.local\bin\uv.exe"
    if not os.path.exists(uv_binary):
        uv_binary = "uv"  # fallback to PATH
        
    # Stage 1 & 2: Run standard orchestrator to extract documents
    state.logs.append("[System] Stage 1: Running document intake and extraction...\n")
    cmd_orch = [
        uv_binary, "run", 
        "--with", "pypdf", 
        "--with", "cryptography",
        "--with", "pymupdf",
        "--with", "pdf2image",
        "python", "-u", "orchestrator.py", "--docs-dir", str(RAW_DOCS_DIR)
    ]
    
    try:
        # Launch subprocess for extraction
        proc = subprocess.Popen(
            cmd_orch,
            cwd=str(WORKSPACE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        state.process = proc
        
        # Read output line by line
        for line in proc.stdout:
            state.logs.append(line)
            if len(state.logs) > 2000:
                state.logs.pop(0)
                
        proc.wait()
        
        if proc.returncode != 0:
            state.logs.append(f"\n[System Error] Extraction failed with exit code {proc.returncode}\n")
            return
            
        # Stage 3: If optimized mode, execute the multi-run filing candidate selection
        if mode == "optimized":
            state.logs.append(f"\n[System] Stage 2: Starting Multi-Run Tax Prep Optimization ({runs} runs)...\n")
            cmd_multi = [
                uv_binary, "run", "python", "-u", "run_filing.py", "--runs", str(runs)
            ]
            proc_multi = subprocess.Popen(
                cmd_multi,
                cwd=str(WORKSPACE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            state.process = proc_multi
            
            for line in proc_multi.stdout:
                state.logs.append(line)
                if len(state.logs) > 2000:
                    state.logs.pop(0)
                    
            proc_multi.wait()
            
            if proc_multi.returncode != 0:
                state.logs.append(f"\n[System Error] Multi-run optimization failed with exit code {proc_multi.returncode}\n")
                return
                
        state.logs.append(f"\n[System] Orchestration successfully completed!\n")
    except Exception as e:
        import traceback
        traceback.print_exc()
        state.logs.append(f"\n[System Error] Failed to run: {type(e).__name__}: {str(e)}\n")
    finally:
        state.running = False
        state.process = None

@app.post("/api/run")
def trigger_swarm(payload: RunPayload = None):
    import threading
    if state.running:
        return {"status": "already_running"}
        
    mode = "standard"
    runs = 5
    if payload:
        mode = payload.mode
        runs = payload.runs
        
    thread = threading.Thread(target=run_orchestrator_sync, args=(mode, runs))
    thread.start()
    return {"status": "started"}

@app.get("/api/logs")
def get_logs():
    return {"running": state.running, "logs": "".join(state.logs)}

@app.get("/api/report")
def get_report():
    if not TAX_PREP_REPORT_PATH.exists():
        raise HTTPException(status_code=404, detail="Tax prep report not generated yet.")
        
    with open(TAX_PREP_REPORT_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    return {"markdown": content}

@app.get("/api/forms/download/{filename}")
def download_form(filename: str):
    # Security check: restrict to filled_forms directory
    filepath = FILLED_FORMS_DIR / filename
    if not filepath.exists() or filepath.parent != FILLED_FORMS_DIR:
        raise HTTPException(status_code=404, detail="Form not found.")
        
    return FileResponse(filepath, media_type="application/pdf", filename=filename)

# Chat Interface schemas
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatPayload(BaseModel):
    messages: list[ChatMessage]

@app.post("/api/chat")
async def chat_gemma(payload: ChatPayload):
    # 1. Enforce privacy firewall
    ollama_url = f"{OLLAMA_HOST}/api/chat"
    _assert_local_host(ollama_url)

    # 2. Resolve Gemma model
    gemma_model = resolve_gemma_model()
    
    # 2. Gather context
    tax_data_content = "{}"
    if TAX_DATA_PATH.exists():
        try:
            with open(TAX_DATA_PATH, "r", encoding="utf-8") as f:
                tax_data_content = f.read()
        except Exception:
            pass
            
    tax_prep_report_content = "No report generated yet."
    if TAX_PREP_REPORT_PATH.exists():
        try:
            with open(TAX_PREP_REPORT_PATH, "r", encoding="utf-8") as f:
                tax_prep_report_content = f.read()
        except Exception:
            pass
            
    # Gather code file details
    script_details = (
        "- orchestrator.py: Coordinates the multi-agent swarm stages (Sorter, Reader, Advisor, Filer).\n"
        "- form_generator.py: Python script using pypdf to fill official tax forms (1040, Schedule 1/C/E, 8582, 2210, CA 540NR, MI-1040) from JSON data.\n"
        "- download_forms.py: Downloads IRS and state PDF templates into final_outputs/templates/.\n"
        "- inspect_fields.py: Examines official PDF templates to output field structure maps.\n"
        "- app.py: The current FastAPI backend managing dashboard and local Gemma chat interactions.\n"
        "- static/index.html: The dashboard front-end interface."
    )
    
    # 3. Formulate the system prompt
    system_prompt = (
        "You are Gemma, a helpful tax assistant running locally. You are part of a local tax preparation workspace.\n"
        "Here is the context of the user's tax profile, findings, and current workspace files:\n\n"
        "=== CODES & SCRIPTS IN WORKSPACE ===\n"
        f"{script_details}\n\n"
        "=== EXTRACTED TAX DATA (JSON) ===\n"
        f"{tax_data_content}\n\n"
        "=== TAX PREPARATION & ACTION PLAN ===\n"
        f"{tax_prep_report_content}\n\n"
        "INSTRUCTIONS FOR CHAT:\n"
        "1. Answer questions about the tax prep report, calculations (penalties, standard deduction, safe harbor, passive loss limit), or needed files.\n"
        "2. Be aware that the user works with Antigravity (a powerful developer agent) who can make changes to these scripts.\n"
        "3. If the user discusses changes they want to make (e.g. adding new forms, tweaking tax bracket calculations, changing logic), explain how they can ask Antigravity to modify orchestrator.py, form_generator.py, etc., and brainstorm the code modifications with them.\n"
        "4. DO NOT write code to modify files directly (you are a chat assistant, not a workspace operator), but provide clear, logical ideas or code snippets that the user can feed to Antigravity.\n"
        "5. Keep responses structured, concise, and professional."
    )
    
    # 4. Formulate the Ollama chat payload
    ollama_messages = [{"role": "system", "content": system_prompt}]
    for msg in payload.messages:
        ollama_messages.append({"role": msg.role, "content": msg.content})
        
    url = f"{OLLAMA_HOST}/api/chat"
    req_payload = {
        "model": gemma_model,
        "messages": ollama_messages,
        "stream": False
    }
    
    try:
        data = json.dumps(req_payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        
        # We can't await this blocking request easily without standard httpx/aiohttp, but since we are running locally 
        # on localhost, we can use a run_in_executor to avoid blocking the event loop!
        def call_ollama():
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode("utf-8"))
                
        loop = asyncio.get_event_loop()
        res_data = await loop.run_in_executor(None, call_ollama)
        response_content = res_data["message"]["content"]
        
        return {"response": response_content, "model": gemma_model}
        
    except Exception as e:
        # Fallback error response
        error_msg = f"Failed to connect to local Ollama. Please check if Ollama is running. Error: {str(e)}"
        return {"response": error_msg, "model": gemma_model}

# Serve static files
static_dir = WORKSPACE_DIR / "static"
static_dir.mkdir(exist_ok=True)

# Mount static files to serve dashboard
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
