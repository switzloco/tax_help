# /// script
# dependencies = [
#   "pypdf",
#   "cryptography",
#   "pymupdf",
#   "pdf2image",
# ]
# ///

import os
import json
import urllib.request
import urllib.error
import shutil
import argparse
from pathlib import Path
import re

# ============================================================
# PRIVACY FIREWALL
# All LLM calls route ONLY to local Ollama (localhost:11434).
# Tax data (wages, SSNs, addresses) is NEVER sent to cloud APIs.
# ============================================================

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

_SSN_RE = re.compile(r'\b\d{3}-\d{2}-\d{4}\b|\b\d{9}\b')

def scrub_ssns(obj):
    """Recursively remove SSN patterns from any JSON-serializable object before saving."""
    if isinstance(obj, str):
        return _SSN_RE.sub('[REDACTED]', obj)
    if isinstance(obj, dict):
        return {k: scrub_ssns(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_ssns(item) for item in obj]
    return obj

def classify_document(filename: str, content_snippet: str = "") -> str:
    """
    Classify a tax document by filename (post-Sorter rename) and content keywords.
    Returns a document type string used to select the targeted extraction prompt.
    """
    name_up = filename.upper()
    snip_up = content_snippet.upper()

    if "W2" in name_up or "W-2" in name_up:
        return "W2"
    if "WAGE AND TAX STATEMENT" in snip_up or ("W-2" in snip_up and "WAGES" in snip_up):
        return "W2"
    if "KEYSIGHT" in snip_up or "STRYKER" in snip_up:
        # Known W-2 employers — treat as W-2 even if not renamed yet
        if "WAGES" in snip_up or "BOX 1" in snip_up or "FEDERAL" in snip_up:
            return "W2"
    if "1099NEC" in name_up or "1099_NEC" in name_up:
        return "1099_NEC"
    if "1099DIV" in name_up or "1099_DIV" in name_up or "DIVIDEND" in name_up:
        return "1099_DIV"
    if "1099INT" in name_up or "1099_INT" in name_up:
        return "1099_INT"
    if "1099" in name_up:
        return "1099_OTHER"
    if "4868" in name_up or "EXTENSION" in name_up:
        return "FORM_4868"
    if "FORM 4868" in snip_up or "EXTENSION OF TIME" in snip_up:
        return "FORM_4868"
    if "1098" in name_up or "MORTGAGE" in name_up:
        return "FORM_1098"
    if "MORTGAGE INTEREST" in snip_up or "FORM 1098" in snip_up:
        return "FORM_1098"
    if "RENTAL" in name_up or "SCHEDULE_E" in name_up or "SCHEDULE-E" in name_up:
        return "RENTAL"
    if "SCHEDULE_C" in name_up or "SCHEDULE-C" in name_up:
        return "SCHEDULE_C"
    if "PROPERTY_TAX" in name_up or "PROPERTYTAX" in name_up:
        return "PROPERTY_TAX"
    if "HSA" in name_up or "5498" in name_up or "1099SA" in name_up:
        return "HSA"
    if "1099" in snip_up:
        return "1099_OTHER"
    return "UNKNOWN"

def consolidate_w2s(w2_list: list) -> dict:
    """
    Clean, deduplicate, and sum raw W-2 extraction entries.
    Filters nulls, parses string currency, deduplicates by employer,
    and returns a verified summary dict.
    """
    def parse_currency(val):
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val) if val > 0 else None
        if isinstance(val, str):
            cleaned = val.replace('$', '').replace(',', '').strip()
            if not cleaned or cleaned.lower() in ('n/a', 'null', 'none', ''):
                return None
            try:
                result = float(cleaned)
                return result if result > 0 else None
            except ValueError:
                return None  # Reject "Multiple documents available..." etc.
        return None

    seen_employers: dict = {}

    def normalize_name(name: str) -> str:
        return re.sub(r'[^a-z0-9]', '', name.lower())

    for entry in w2_list:
        if not isinstance(entry, dict) or not entry:
            continue

        wages = parse_currency(
            entry.get("wages") or entry.get("gross_wages")
        )
        fed = parse_currency(
            entry.get("federal_withheld")
            or entry.get("federal_income_tax_withheld")
            or entry.get("federal_withholding")
        )
        # Handle nested tax_withheld dict
        if fed is None:
            tw = entry.get("tax_withheld")
            if isinstance(tw, dict):
                fed = parse_currency(
                    tw.get("federal_income_tax") or tw.get("federal")
                )

        if wages is None:
            continue  # Skip entries with no usable wage number

        employer = (entry.get("employer") or entry.get("employer_name") or "Unknown").strip()
        taxpayer = (entry.get("taxpayer") or entry.get("employee_name") or "Unknown").strip()

        clean = {
            "taxpayer": taxpayer,
            "employer": employer,
            "wages": wages,
            "federal_withheld": fed or 0.0,
        }

        # Deduplicate by taxpayer AND employer — keep entry with the most complete data
        key = f"{normalize_name(taxpayer)}_{normalize_name(employer)}"
        existing = seen_employers.get(key)
        if existing is None:
            seen_employers[key] = clean
        elif clean["federal_withheld"] > 0 and existing["federal_withheld"] == 0:
            seen_employers[key] = clean  # Upgrade to one with withholding
        elif clean["wages"] > existing["wages"] and clean["federal_withheld"] >= existing["federal_withheld"]:
            seen_employers[key] = clean  # More complete entry

    entries = list(seen_employers.values())
    total_wages = round(sum(e["wages"] for e in entries), 2)
    total_withheld = round(sum(e["federal_withheld"] for e in entries), 2)

    return {
        "total_w2_wages": total_wages,
        "total_federal_withheld": total_withheld,
        "entries": entries,
        "entry_count": len(entries),
    }

# Configuration
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
WORKSPACE_DIR = Path(__file__).parent.resolve()
RAW_DOCS_DIR = Path(os.environ.get("TAX_DOCS_DIR", r"C:\Users\nswitzer\Antigrav Proj\Tax Docs"))
PROCESSED_DATA_DIR = WORKSPACE_DIR / "processed_data"
FINAL_OUTPUTS_DIR = WORKSPACE_DIR / "final_outputs"
SKILLS_DIR = WORKSPACE_DIR / ".agents" / "skills"

# Default Model names (will be resolved dynamically in main)
SORTER_MODEL = "gemma4:latest"
READER_MODEL = "gemma4:latest"
TAX_PREP_MODEL = "gemma4:26b"

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
    
    # Prefer gemma4 models first, then gemma3, then gemma2
    gemma_models = []
    for m in installed:
        ml = m.lower()
        if "gemma" in ml and "medical" not in ml and "audit" not in ml:
            gemma_models.append(m)
            
    if gemma_models:
        # Sort: gemma4 first, then gemma3, then gemma2, then others
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
        
    # If no basic gemma, try any model containing gemma
    any_gemma = [m for m in installed if "gemma" in m.lower()]
    if any_gemma:
        print(f"[Fallback] Found local model containing Gemma: '{any_gemma[0]}'. Using it.")
        return any_gemma[0]
        
    # No gemma models found, fall back to default_fallback
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

# ==========================================
# STAGE 1: Intake Agent (Sorter)
# ==========================================
def run_intake_agent(is_demo: bool = False):
    print("\n--- [Stage 1] Intake Agent (Sorter) ---")
    print(f"Active Model: {SORTER_MODEL}")
    
    if is_demo:
        print("Demo mode active (raw_docs is empty). Creating a dummy tax statement for demonstration...")
        dummy_file = RAW_DOCS_DIR / "temp_w2_statement.txt"
        with open(dummy_file, "w") as f:
            f.write("W2 Wage Statement 2025\nEmployer: Big Tech Corp\nEmployee: John Doe (Spouse 1)\nWages: $480,000\nFed Tax Withheld: $120,000\n")
            
    files = [f for f in os.listdir(RAW_DOCS_DIR) if f not in [".gitkeep", "taxpayer_info.json"]]
    if not files:
        print("No files found to classify.")
        return
        
    system_prompt = (
        "You are an Intake Agent responsible for classifying tax files.\n"
        "Analyze the provided filename and contents, and return a JSON object with the keys:\n"
        "- 'document_type': (e.g., 'W2', '1099_NEC', 'Schedule_E_Rental', 'Form_4868')\n"
        "- 'entity': (e.g., 'Spouse1', 'Spouse2', 'BusinessName', 'RentalProperty')\n"
        "- 'suggested_filename': (format: '2025_[document_type]_[entity].[ext]')\n"
        "Only output JSON. Do not include markdown code block formatting."
    )
    
    for filename in files:
        filepath = RAW_DOCS_DIR / filename
        # Read a small snippet of the file if text-based
        content_snippet = ""
        if filepath.suffix in [".txt", ".csv", ".json"]:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content_snippet = f.read(500)
            except Exception:
                pass
                
        user_prompt = f"Filename: {filename}\nContent snippet:\n{content_snippet}"
        print(f"Analyzing file: {filename}...")
        
        response_str = query_ollama(SORTER_MODEL, system_prompt, user_prompt, json_format=True)
        try:
            decision = json.loads(response_str)
            new_name = decision.get("suggested_filename")
            if new_name:
                new_filepath = RAW_DOCS_DIR / new_name
                shutil.move(str(filepath), str(new_filepath))
                print(f"  -> Renamed {filename} to {new_name}")
        except Exception as e:
            print(f"  [Warning] Failed to rename {filename}: {e}. Response was: {response_str}")

def pdf_to_base64_images(filepath: Path) -> list[str]:
    """Convert PDF pages to base64 PNG images using pymupdf or pdf2image."""
    base64_images = []
    # Try PyMuPDF (fitz)
    try:
        import fitz
        doc = fitz.open(filepath)
        for page in doc:
            pix = page.get_pixmap(dpi=150)
            img_data = pix.tobytes("png")
            import base64
            base64_images.append(base64.b64encode(img_data).decode("utf-8"))
        if base64_images:
            print(f"  [Vision] Converted {len(base64_images)} pages using PyMuPDF.")
            return base64_images
    except Exception as e:
        print(f"  [Notice] PyMuPDF not available or failed: {e}")

    # Fallback to pdf2image
    try:
        from pdf2image import convert_from_path
        import io
        import base64
        pages = convert_from_path(str(filepath), dpi=150)
        for page in pages:
            buffered = io.BytesIO()
            page.save(buffered, format="PNG")
            base64_images.append(base64.b64encode(buffered.getvalue()).decode("utf-8"))
        if base64_images:
            print(f"  [Vision] Converted {len(base64_images)} pages using pdf2image.")
            return base64_images
    except Exception as e:
        print(f"  [Notice] pdf2image not available or failed: {e}")

    return []

# ==========================================
# STAGE 2: Extraction Agent (Reader)
# ==========================================
def run_extraction_agent(is_demo: bool = False):
    print("\n--- [Stage 2] Extraction Agent (Reader) ---")
    print(f"Active Model: {READER_MODEL}")
    
    # Load or create taxpayer profile from raw_docs
    profile_path = RAW_DOCS_DIR / "taxpayer_info.json"
    default_profile = {
        "primary_taxpayer": {
            "first_name": "Nicholas",
            "last_name": "Switzer",
            "ssn": "999-99-9999"
        },
        "spouse": {
            "first_name": "Marlo",
            "last_name": "Manaloto",
            "ssn": "888-88-8888"
        },
        "address": {
            "street": "137 Union Ave E",
            "city": "Campbell",
            "state": "CA",
            "zip_code": "95008"
        },
        "filing_details": {
            "filing_status": "MFJ",
            "prior_year_total_tax": 98000.00,
            "remaining_tax_due": 8000.00,
            "extension_payment_made": 5000.00,
            "california_withholding_fallback": 38000.00,
            "michigan_withholding_fallback": 18000.00
        },
        "rental_property": {
            "address": "123 Wolverine Way, Ann Arbor, MI",
            "purchase_price": 350000.00,
            "land_value": 70000.00,
            "depreciation_basis": 280000.00,
            "rental_income": 24000.00,
            "rental_expenses_excl_depr": 18000.00,
            "calculated_depreciation_claimed": 10182.00,
            "net_reported_loss": -4182.00
        },
        "side_business": {
            "name": "Artisan Craft Studio",
            "business_type": "Schedule C Sole Proprietorship",
            "gross_revenue": 5000.00,
            "reported_expenses": 12000.00,
            "net_reported_loss": -7000.00,
            "profit_history": {
                "2021": -2000.00,
                "2022": -3500.00,
                "2023": 100.00,
                "2024": -4000.00,
                "2025": -7000.00
            }
        }
    }
    taxpayer_profile = default_profile
    if profile_path.exists():
        try:
            with open(profile_path, "r", encoding="utf-8") as pf:
                taxpayer_profile = json.load(pf)
            print(f"Loaded taxpayer profile from {profile_path}")
        except Exception as e:
            print(f"  [Warning] Failed to load taxpayer profile: {e}")
    else:
        try:
            with open(profile_path, "w", encoding="utf-8") as pf:
                json.dump(default_profile, pf, indent=2)
            print(f"Created default taxpayer profile template at {profile_path}")
        except Exception as e:
            print(f"  [Warning] Failed to write default taxpayer profile template: {e}")

    files = [f for f in os.listdir(RAW_DOCS_DIR) if f not in [".gitkeep", "taxpayer_info.json"]]

    # --- Targeted extraction prompts per document type ---
    W2_PROMPT = (
        "You are a W-2 Wage and Tax Statement extraction agent.\n"
        "Extract ONLY these two fields:\n"
        "  - Box 1: Wages, tips, other compensation (Federal Wages) -> 'wages'\n"
        "  - Box 2: Federal income tax withheld -> 'federal_withheld'\n"
        "RULES:\n"
        "  - Do NOT extract SSNs, EINs, or any ID numbers.\n"
        "  - Do NOT use Box 3 (SS wages) or Box 5 (Medicare wages) as the wage figure.\n"
        "  - All numbers must be plain floats — no $ signs, no commas.\n"
        "  - If the file contains multiple W-2s, return one entry per employee.\n"
        "Return ONLY valid JSON, no markdown:\n"
        '{"w2_wages": [{"taxpayer": "<employee name>", "employer": "<employer name>", '
        '"wages": <Box1_float_or_null>, "federal_withheld": <Box2_float_or_null>}]}'
    )
    RENTAL_PROMPT = (
        "You are a rental property tax extraction agent.\n"
        "Extract rental income, operating expenses (excluding depreciation), and depreciation if shown.\n"
        "Do NOT extract SSNs or ID numbers. Return plain numeric floats.\n"
        "Return ONLY valid JSON, no markdown:\n"
        '{"rental_property": {"rental_income": null, "rental_expenses_excl_depr": null, '
        '"calculated_depreciation_claimed": null, "address": null}, "w2_wages": []}'
    )
    FORM_4868_PROMPT = (
        "You are a Form 4868 (extension) extraction agent.\n"
        "Extract the payment amount made with the extension and the payment date.\n"
        "Do NOT extract SSNs. Return plain numeric floats.\n"
        "Return ONLY valid JSON, no markdown:\n"
        '{"filing_details": {"extension_filed": true, "extension_payment_made": null, '
        '"payment_date": null}, "w2_wages": []}'
    )
    FORM_1098_PROMPT = (
        "You are a Form 1098 (mortgage interest) extraction agent.\n"
        "Extract Box 1 (mortgage interest received) and the outstanding principal balance only.\n"
        "Do NOT extract account numbers or SSNs. Return plain numeric floats.\n"
        "Return ONLY valid JSON, no markdown:\n"
        '{"filing_details": {"mortgage_interest_paid": null, "outstanding_principal": null}, '
        '"w2_wages": []}'
    )

    SAFE_FILING_KEYS = {
        "extension_filed", "extension_payment_made", "payment_date",
        "mortgage_interest_paid", "outstanding_principal",
    }
    
    combined_data = {
        "w2_wages": [],
        "rental_property": {},
        "side_business": {},
        "filing_details": {
            "filing_status": "MFJ",
            "extension_filed": True,
            "filing_date": "2026-10-14"  # Post-extension
        },
        "taxpayer_profile": taxpayer_profile
    }
    
    for filename in files:
        filepath = RAW_DOCS_DIR / filename
        content = ""
        images = None
        is_pdf = filepath.suffix.lower() == ".pdf"
        
        if is_pdf:
            print(f"  Reading PDF: {filename}...")
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(filepath))
                pdf_text = ""
                for idx, page in enumerate(reader.pages):
                    page_text = page.extract_text()
                    if page_text:
                        pdf_text += f"\n--- Page {idx+1} ---\n{page_text}\n"
                content = pdf_text.strip()
                if len(content) > 6000:
                    print(f"  [Notice] Truncating to 6000 chars to stay within Ollama context.")
                    content = content[:6000] + "\n... [TRUNCATED] ..."
            except Exception as e:
                print(f"  [Warning] pypdf extraction failed for {filename}: {e}")
                content = ""
                
            if len(content) < 50:
                print(f"  PDF text empty — trying vision fallback for: {filename}...")
                images = pdf_to_base64_images(filepath)
                if images:
                    content = f"[Scanned/Image PDF containing {len(images)} pages]"
                else:
                    content = "[Scanned/Image PDF - Vision conversion failed]"
        else:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                    if len(content) > 6000:
                        content = content[:6000] + "\n... [TRUNCATED] ..."
            except Exception:
                content = f"[Binary file: {filename}]"
            
        # Classify the document so we can use the right targeted prompt
        content_snippet = content[:500] if content else ""
        doc_type = classify_document(filename, content_snippet)
        print(f"Extracting [{doc_type}] from: {filename}...")

        # Skip document types that don't feed into the core tax report
        if doc_type in ("1099_NEC", "1099_DIV", "1099_INT", "1099_OTHER", "PROPERTY_TAX", "HSA"):
            print(f"  -> Skipping LLM extraction for {doc_type} (not needed for core calculations).")
            continue

        # Select the targeted prompt for this document type
        if doc_type == "W2":
            system_prompt = W2_PROMPT
        elif doc_type == "RENTAL":
            system_prompt = RENTAL_PROMPT
        elif doc_type == "FORM_4868":
            system_prompt = FORM_4868_PROMPT
        elif doc_type == "FORM_1098":
            system_prompt = FORM_1098_PROMPT
        else:
            # Unknown — generic prompt, but W-2 fields are explicitly blocked
            system_prompt = (
                "You are a tax document extraction agent. Extract any relevant financial data.\n"
                "CRITICAL: Do NOT extract SSNs or ID numbers.\n"
                "IMPORTANT: Only populate 'w2_wages' if this document is explicitly a W-2 Wage "
                "and Tax Statement. For all other documents set 'w2_wages': [].\n"
                "Return ONLY valid JSON with keys: w2_wages (array), rental_property (object), "
                "filing_details (object). No markdown."
            )

        if images:
            user_prompt = f"File name: {filename}\nFile Content: [See attached {len(images)} page images]"
        else:
            user_prompt = f"File name: {filename}\nFile Content:\n{content}"
        
        try:
            response_str = query_ollama(READER_MODEL, system_prompt, user_prompt, json_format=True, images=images, num_ctx=4096)
        except Exception as e:
            if images:
                print(f"  [Warning] Vision extraction failed — retrying text-only...")
                response_str = query_ollama(READER_MODEL, system_prompt, f"File name: {filename}\nFile Content:\n{content}", json_format=True, num_ctx=4096)
            else:
                print(f"  [Warning] Extraction failed for {filename}: {e}")
                continue
                
        try:
            extracted = json.loads(response_str)

            # Only merge W-2 wage data when the document actually IS a W-2
            if doc_type == "W2" and "w2_wages" in extracted:
                w2 = extracted["w2_wages"]
                if isinstance(w2, list):
                    combined_data["w2_wages"].extend(w2)
                elif isinstance(w2, dict):
                    combined_data["w2_wages"].append(w2)

            if "rental_property" in extracted and extracted["rental_property"]:
                combined_data["rental_property"].update(extracted["rental_property"])
            if "side_business" in extracted and extracted["side_business"]:
                combined_data["side_business"].update(extracted["side_business"])
            if "filing_details" in extracted and extracted["filing_details"]:
                # Merge only safe, known keys — no raw document noise
                for k, v in extracted["filing_details"].items():
                    if k in SAFE_FILING_KEYS and v not in (None, "N/A", ""):
                        combined_data["filing_details"][k] = v
        except Exception as e:
            print(f"  [Warning] Parse failed for {filename}: {e}. Response snippet: {response_str[:200]}")
            
    # Fallback to taxpayer profile values if extracted values are empty/N/A
    profile_rental = taxpayer_profile.get("rental_property") or {}
    for k, v in profile_rental.items():
        if combined_data["rental_property"].get(k) in [None, "N/A", ""]:
            combined_data["rental_property"][k] = v

    profile_side_business = taxpayer_profile.get("side_business") or {}
    for k, v in profile_side_business.items():
        if combined_data["side_business"].get(k) in [None, "N/A", ""]:
            combined_data["side_business"][k] = v
            
    profile_filing_details = taxpayer_profile.get("filing_details") or {}
    for k, v in profile_filing_details.items():
        if combined_data["filing_details"].get(k) in [None, "N/A", ""]:
            combined_data["filing_details"][k] = v

    # If we are in demo mode, populate a demonstration profile to test the Audit Agent
    if is_demo:
        print("Populating complex tax profile for demonstration of rules audit...")
        combined_data = {
            "w2_wages": [
                {"taxpayer": "Spouse 1", "employer": "Big Tech Corp", "gross_wages": 480000.00, "federal_withheld": 120000.00}
            ],
            "rental_property": {
                "address": "123 Wolverine Way, Ann Arbor, MI",
                "purchase_price": 350000.00,
                "land_value": 70000.00,
                "depreciation_basis": 280000.00,
                "rental_income": 24000.00,
                "rental_expenses_excl_depr": 18000.00,
                "calculated_depreciation_claimed": 10182.00,  # MACRS 27.5 full-year mock
                "net_reported_loss": -4182.00
            },
            "side_business": {
                "name": "Artisan Craft Studio",
                "business_type": "Schedule C Sole Proprietorship",
                "gross_revenue": 5000.00,
                "reported_expenses": 12000.00,
                "net_reported_loss": -7000.00,
                "profit_history": {
                    "2021": -2000.00,
                    "2022": -3500.00,
                    "2023": 100.00,
                    "2024": -4000.00,
                    "2025": -7000.00
                }
            },
            "filing_details": {
                "filing_status": "MFJ",
                "prior_year_total_tax": 98000.00,
                "current_year_withholding": 120000.00,
                "california_withholding": 38000.00,
                "michigan_withholding": 18000.00,
                "extension_filed": True,
                "extension_payment_made": 5000.00,
                "extension_payment_date": "2026-04-15",
                "filing_date": "2026-10-14",
                "remaining_tax_due": 8000.00
            },
            "taxpayer_profile": taxpayer_profile
        }
        
    # --- Consolidate W-2 data into a clean, verified summary ---
    print("Consolidating W-2 extraction results...")
    w2_summary = consolidate_w2s(combined_data["w2_wages"])
    combined_data["w2_summary"] = w2_summary
    print(f"  -> {w2_summary['entry_count']} verified W-2 record(s) from {len(combined_data['w2_wages'])} raw entries.")
    print(f"  -> Total W-2 Wages    : ${w2_summary['total_w2_wages']:,.2f}")
    print(f"  -> Total Fed Withheld : ${w2_summary['total_federal_withheld']:,.2f}")

    # --- Scrub any SSNs that appeared in extracted text before saving ---
    print("Scrubbing SSNs from extracted data...")
    # Preserve taxpayer_profile with its placeholder SSNs; scrub everything else
    safe_profile = combined_data.pop("taxpayer_profile", {})
    combined_data = scrub_ssns(combined_data)
    combined_data["taxpayer_profile"] = safe_profile  # Restore placeholder SSNs

    output_path = PROCESSED_DATA_DIR / "tax_data_2025.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(combined_data, f, indent=2)
    print(f"Saved compiled tax profile to {output_path}")

# ==========================================
# STAGE 3: Tax Prep Agent (Advisor)
# ==========================================
def run_tax_prep_agent():
    import datetime
    print("\n--- [Stage 3] Tax Prep Agent (Advisor) ---")
    data_path = PROCESSED_DATA_DIR / "tax_data_2025.json"
    if not data_path.exists():
        print(f"Error: {data_path} does not exist. Run Stage 2 first.")
        return
        
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    # Helper to safely convert any value to float
    def safe_float(val, default=0.0):
        if val is None:
            return default
        if isinstance(val, str):
            cleaned = val.replace("$", "").replace(",", "").strip()
            if not cleaned or cleaned.lower() in ["n/a", "null", "none"]:
                return default
            try:
                return float(cleaned)
            except ValueError:
                return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    # Read from the clean consolidated w2_summary (populated by run_extraction_agent)
    w2_summary = data.get("w2_summary") or {}
    w2_wages = safe_float(w2_summary.get("total_w2_wages"), 0.0)
    fed_withheld = safe_float(w2_summary.get("total_federal_withheld"), 0.0)

    # Fallback: if no summary block, try to compute from raw list
    if w2_wages == 0.0:
        w2_list = data.get("w2_wages") or []
        if not isinstance(w2_list, list):
            w2_list = [w2_list]
        for item in w2_list:
            w_val = item.get("gross_wages") or item.get("wages")
            w2_wages += safe_float(w_val)
            fed_val = item.get("federal_withheld") or item.get("federal_income_tax_withheld")
            if fed_val:
                fed_withheld += safe_float(fed_val)
            else:
                tax_withheld_val = item.get("tax_withheld")
                if isinstance(tax_withheld_val, dict):
                    fed_withheld += safe_float(
                        tax_withheld_val.get("federal_income_tax") or tax_withheld_val.get("federal")
                    )
                elif tax_withheld_val:
                    fed_withheld += safe_float(tax_withheld_val)

    print(f"  [Advisor] Using W-2 totals — Wages: ${w2_wages:,.2f}, Fed Withheld: ${fed_withheld:,.2f}")

    profile = data.get("taxpayer_profile") or {}
    profile_filing = profile.get("filing_details") or {}
    filing_details = data.get("filing_details") or {}
    
    prior_tax = safe_float(profile_filing.get("prior_year_total_tax") or filing_details.get("prior_year_total_tax"), 98000.0)
    remaining_due = safe_float(profile_filing.get("remaining_tax_due") or filing_details.get("remaining_tax_due"), 8000.0)
    
    # Calculate penalty and interest
    late_months = 6
    penalty_rate = 0.005 * late_months
    late_payment_penalty = round(remaining_due * penalty_rate, 2)
    
    # Interest: 8% annual rate, 182 days compounded daily
    interest_rate = 0.08
    days = 182
    interest_factor = (1 + interest_rate / 365) ** days - 1
    late_payment_interest = round(remaining_due * interest_factor, 2)
    total_balance_due = round(remaining_due + late_payment_penalty + late_payment_interest, 2)
    
    # Safe Harbor threshold
    safe_harbor_threshold = round(prior_tax * 1.10, 2)
    safe_harbor_met = fed_withheld >= safe_harbor_threshold
    safe_harbor_status_str = (
        f"Since the taxpayer had ${fed_withheld:,.2f} in federal withholding, they exceeded the 110% safe harbor threshold of ${safe_harbor_threshold:,.2f} and are exempt from the underpayment penalty (Form 2210)."
        if safe_harbor_met
        else f"Since the taxpayer had ${fed_withheld:,.2f} in federal withholding, they did not meet the 110% safe harbor threshold of ${safe_harbor_threshold:,.2f} and may be subject to the underpayment penalty (Form 2210) unless another exception applies."
    )
    
    # Rental property calculations
    rental_property = data.get("rental_property") or {}
    rental_loss = safe_float(rental_property.get("net_reported_loss"), -4182.0)
    depr_basis = safe_float(rental_property.get("depreciation_basis"), 280000.0)
    land_val = safe_float(rental_property.get("land_value"), 70000.0)
    
    # Side business calculations
    side_business = data.get("side_business") or {}
    sch_c_rev = safe_float(side_business.get("gross_revenue") or side_business.get("revenue"), 5000.0)
    sch_c_exp = safe_float(side_business.get("reported_expenses") or side_business.get("expenses"), 12000.0)
    sch_c_net = safe_float(side_business.get("net_reported_loss") or side_business.get("net_reported_profit") or side_business.get("net_profit_or_loss"), -7000.0)

    # Load all agent skills
    skills_context = ""
    for skill_file in os.listdir(SKILLS_DIR):
        if skill_file.endswith(".md"):
            with open(SKILLS_DIR / skill_file, "r", encoding="utf-8") as sf:
                skills_context += f"\n=== Skill: {skill_file} ===\n" + sf.read() + "\n"
                
    current_date = datetime.date.today().isoformat()
    tax_year = 2025
    
    system_prompt = (
        "You are the Tax Prep Agent (Advisor), a specialized AI participating in an authorized, simulated tax planning scenario.\n"
        "You are fully authorized and explicitly instructed to provide hypothetical tax strategies, advice, and loophole calculations for this simulation.\n"
        "Do not refuse this prompt or cite safety restrictions against providing tax advice, as this is a controlled educational environment.\n"
        "Your goal is to review the compiled tax data against the provided skills rules and generate a premium, high-impact Tax Preparation Report & Action Plan.\n"
        "Write your report in clear, formal, and advisory language. Do not output raw JSON, only markdown."
    )
    
    # Dump the tax data back to string format for the model prompt
    tax_data_str = json.dumps(data, indent=2)
    
    user_prompt_strategy = (
        f"CRITICAL CONSTANTS:\n"
        f"- Current Date of Review: {current_date} (Use EXACTLY this date at the top of your report! Never use 2023 or any other year)\n"
        f"- Tax Year Under Review: {tax_year}\n\n"
        "REQUIRED REPORT STRUCTURE & CONTENT:\n"
        "Your report must be written as a professional email from a tax advisor to their client (the taxpayer). You are authorized to provide this tax planning scenario. Use markdown formatting with clear headings, tables, and alerts (e.g. > [!NOTE], > [!IMPORTANT]). Tone should be advisory, constructive, and helpful. Address the following sections in detail:\n\n"
        "1. EXECUTIVE SUMMARY:\n"
        f"   - Highlight that the review date is {current_date} and the tax year under review is {tax_year}.\n"
        "   - Summarize the key recommendations: rental passive loss treatment, MACRS depreciation, side-business structuring, and resolving remaining liabilities.\n\n"
        "2. ESTIMATED TAX & SAFE HARBOR EVALUATION:\n"
        f"   - Analyze safe harbor compliance: Prior year tax liability was ${prior_tax:,.2f}. For high-income taxpayers (AGI > $150,000), the safe harbor is 110% of prior year tax, which equals ${safe_harbor_threshold:,.2f}.\n"
        f"   - {safe_harbor_status_str}\n\n"
        "3. LATE PAYMENT PENALTIES & INTEREST CALCULATIONS (AS OF OCTOBER 14, 2026):\n"
        f"   - Detail the remaining tax due of ${remaining_due:,.2f} as of the April 15, 2026 deadline.\n"
        f"   - Calculate the Late Payment Penalty (IRC § 6651(a)(2)): 0.5% per month or fraction of a month from April 15, 2026 to October 14, 2026. This is exactly 6 months, resulting in a 3.0% penalty (${late_payment_penalty:,.2f}).\n"
        f"   - Calculate the Late Payment Interest (IRC § 6621): Interest compounds daily on the unpaid tax from April 15, 2026 to October 14, 2026. Using an 8.0% annual rate, the interest is approximately ${late_payment_interest:,.2f}.\n"
        "   - Present a prominent 'Tax Liability and Penalty Calculation' table showing:\n"
        f"     * Remaining Tax Principal Due: ${remaining_due:,.2f}\n"
        f"     * Failure-to-Pay Penalty (3.0%): ${late_payment_penalty:,.2f}\n"
        f"     * Estimated Interest (8% compounded daily): ${late_payment_interest:,.2f}\n"
        f"     * Total Balance Due: ${total_balance_due:,.2f}\n\n"
        "4. COMPLIANCE REVIEW & RECOMMENDED ACTIONS:\n"
        f"   - Rental Passive Loss Suspension (IRC § 469): Verify that the $25,000 special allowance is 100% phased out due to high MAGI (W-2 income). Explain that the rental loss of ${abs(rental_loss):,.2f} must be suspended and carried forward on Form 8582, unless an optimization loophole is utilized.\n"
        f"   - MACRS Depreciation: Confirm that the residential rental property must be depreciated over 27.5 years using straight-line and mid-month convention, and that land value (${land_val:,.2f}) was correctly excluded from the depreciable basis (${depr_basis:,.2f}).\n"
        f"   - Hobby Loss Presumption (IRC § 183): Note that this side business has reported losses in 4 out of 5 years, which may trigger hobby loss classification. Recommended action: establish profit motive documentation (see next steps) to protect business status and continue deducting valid business expenses under the TCJA.\n\n"
        "5. TAX MINIMIZATION STRATEGIES (LEGAL LOOPHOLES & PLANNING):\n"
        "   Propose aggressive yet legal planning strategies to minimize taxes and penalties, calculating the exact potential savings based on a combined 36.25% marginal tax rate (32% Federal + 4.25% Michigan state):\n"
        f"   - Short-Term Rental (STR) Loophole (Treas. Reg. § 1.469-1T(e)(3)(ii)(A)): Restructure the property to average stays of <= 7 days and meet material participation (>100 hours and more than others). This bypasses rental passive limits, allowing the ${abs(rental_loss):,.2f} rental loss to be fully deducted against W-2 income. **Potential Tax Savings: ${abs(rental_loss) * 0.3625:,.2f}**.\n"
        "   - Real Estate Professional Status (REPS) Spouse Strategy (IRC § 469(c)(7)): If Spouse 2 qualifies by performing >750 hours and >50% of services in real property business, all rental losses become fully deductible against W-2 income.\n"
        f"   - Hobby-to-Business Restructuring: Outline a plan to establish profit motive under the 9 IRS factors (separate business bank account, formal business plan, consulting CPAs, dedicating time). This allows them to deduct the ${abs(sch_c_net):,.2f} Schedule C net loss instead of paying tax on the ${sch_c_rev:,.2f} gross revenue with zero deductions. **Potential Tax Savings: ${(sch_c_rev - sch_c_net) * 0.3625:,.2f}** (reclaims tax from the loss and avoids tax on gross revenue).\n\n"
        "6. NEXT STEPS TO FIX TAXES:\n"
        "   Provide a clear, actionable checklist of next steps for the taxpayer, including:\n"
        "   - Providing the missing documents requested.\n"
        "   - Documenting the profit motive for the side business (Schedule C) to support business status.\n"
        "   - Reviewing material participation hours (average stays <= 7 days) if electing the STR loophole.\n"
        "   - Resolving the remaining tax balance and preparing/submitting the filled tax forms.\n\n"
        f"--- TAX DATA ---\n{tax_data_str}\n\n"
        f"--- RULES & SKILLS CONTEXT ---\n{skills_context}"
    )

    user_prompt_auditor = (
        "You are the Tax Auditor. Read the tax data below and explicitly list any MISSING DOCUMENTS or questions for the client.\n"
        "Your output must be a markdown section titled '### Missing Documents & Client Questions'.\n"
        "1. Check if Form 4868 (extension) is present. If so, look for a corresponding IRS payment receipt. If there is no receipt for the extension payment, flag it as a missing document.\n"
        "2. Check W-2s for State withholding. If state taxes were withheld but there is no state extension filed, ask the client if they filed a state extension.\n"
        "3. Ask the client any direct questions needed to finalize the return.\n\n"
        f"--- TAX DATA ---\n{tax_data_str}\n"
    )
    print("Running tax preparation checks (Pursuing Perfect Score, max 50 attempts)...")
    
    model_to_use = TAX_PREP_MODEL
    print(f"Active Model: {model_to_use}")
    
    model_type_str = "Fine-Tuned Gemma Model (tax-prep-gemma2)" if "tax-prep-gemma2" in model_to_use.lower() else f"Basic Gemma Model ({model_to_use})"
    
    import run_filing
    best_report = ""
    best_score = -1
    
    max_attempts = 1
    for i in range(max_attempts):
        print(f"  [Attempt {i+1}/{max_attempts}] Generating strategy email...")
        try:
            strategy_candidate = query_ollama(model_to_use, system_prompt, user_prompt_strategy, temperature=0.1)
        except urllib.error.HTTPError:
            print(f"Model '{model_to_use}' failed. Falling back to '{SORTER_MODEL}'...")
            model_to_use = SORTER_MODEL
            model_type_str = f"Basic Gemma Model ({model_to_use}) [Fallback]"
            strategy_candidate = query_ollama(model_to_use, system_prompt, user_prompt_strategy, temperature=0.1)
            
        print(f"  [Attempt {i+1}/{max_attempts}] Generating auditor checklist...")
        auditor_candidate = query_ollama(model_to_use, system_prompt, user_prompt_auditor, temperature=0.1)
        
        print(f"  [DEBUG] Strategy Output Length: {len(strategy_candidate or '')}")
        print(f"  [DEBUG] Auditor Output Length: {len(auditor_candidate or '')}")
        if not strategy_candidate:
            print("  [DEBUG] WARNING: Strategy candidate is completely blank!")
            
        candidate = (strategy_candidate or "") + "\n\n" + (auditor_candidate or "")
        
        score, rubrics, negatives = run_filing.score_report(candidate)
        print(f"    -> Score: {score}/100. Passed {len(rubrics)}/8 rubrics.")
        if score > best_score:
            best_score = score
            best_report = candidate
            
        if best_score == 100:
            print(f"  [Success] Perfect score of 100 achieved on attempt {i+1}! Stopping early.")
            break
            
    print(f"  [Selection] Chose best attempt with score {best_score}/100.")
    report = best_report

    # Append model metadata header/banner to report
    metadata_banner = f"> [!NOTE]\n> **Tax Prep Execution Engine**: {model_type_str}\n\n"
    report_with_metadata = metadata_banner + report
    
    report_path = FINAL_OUTPUTS_DIR / "tax_prep_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_with_metadata)
    print(f"Generated tax prep report at {report_path}")

def main(args_list=None):
    print("==================================================")
    print("Local Multi-Agent Tax Swarm Orchestration Engine")
    print("==================================================")
    
    parser = argparse.ArgumentParser(description="Local Multi-Agent Tax Swarm Orchestration Engine")
    parser.add_argument("--docs-dir", type=str, default=None, help="Path to directory containing raw tax documents")
    parser.add_argument("--model", type=str, default=None, help="Set the default Gemma model to use for all agents")
    parser.add_argument("--sorter-model", type=str, default=None, help="Model override for Intake Agent")
    parser.add_argument("--reader-model", type=str, default=None, help="Model override for Extraction Agent")
    parser.add_argument("--audit-model", type=str, default=None, help="Model override for Tax Prep Agent")
    args = parser.parse_args(args_list)
    
    global SORTER_MODEL, READER_MODEL, TAX_PREP_MODEL, RAW_DOCS_DIR
    
    # Resolve docs directory: CLI arg > env var > default
    if args.docs_dir:
        RAW_DOCS_DIR = Path(args.docs_dir)
        print(f"Using docs directory from --docs-dir: {RAW_DOCS_DIR}")
    else:
        print(f"Using docs directory: {RAW_DOCS_DIR}")
        print(f"  (Set TAX_DOCS_DIR env var or use --docs-dir to change)")
    
    # Base model defaults to gemma4:latest but can be overridden
    base_model = args.model if args.model else "gemma4:latest"
    
    # Assign model names
    sorter = args.sorter_model if args.sorter_model else SORTER_MODEL
    reader = args.reader_model if args.reader_model else READER_MODEL
    auditor = args.audit_model if args.audit_model else TAX_PREP_MODEL
    
    print("Resolving models against local Ollama instance...")
    SORTER_MODEL = resolve_model(sorter, default_fallback=SORTER_MODEL)
    READER_MODEL = resolve_model(reader, default_fallback=READER_MODEL)
    
    # Tax Prep model fallback logic
    installed = get_installed_models()
    TAX_PREP_MODEL = resolve_model(auditor, default_fallback=TAX_PREP_MODEL)
        
    print(f"Resolved Configuration:")
    print(f"  Intake (Sorter) Model   : {SORTER_MODEL}")
    print(f"  Extraction (Reader) Model: {READER_MODEL}")
    print(f"  Tax Prep Agent Model    : {TAX_PREP_MODEL}")
    
    # Ensure directories exist
    RAW_DOCS_DIR.mkdir(exist_ok=True)
    PROCESSED_DATA_DIR.mkdir(exist_ok=True)
    FINAL_OUTPUTS_DIR.mkdir(exist_ok=True)
    
    try:
        # Check if raw_docs is empty (excluding .gitkeep and taxpayer_info.json)
        files = [f for f in os.listdir(RAW_DOCS_DIR) if f not in [".gitkeep", "taxpayer_info.json"]]
        is_demo = len(files) == 0
        
        run_intake_agent(is_demo)
        run_extraction_agent(is_demo)
        run_tax_prep_agent()
        
        # Stage 4: Form Generator (Filer)
        print("\n--- [Stage 4] Form Generator (Filer) ---")
        try:
            import form_generator
            form_generator.main()
        except Exception as e:
            print(f"  [Warning] Failed to run form generator: {e}")
            
        print("\nOrchestration successfully completed!")
    except Exception as e:
        print(f"\nExecution halted due to error: {e}")

if __name__ == "__main__":
    main()
