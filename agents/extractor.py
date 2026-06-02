import json
import re
from pathlib import Path
from shared.ollama_client import query_ollama, scrub_ssns
from shared.pdf_reader import pdf_to_base64_images, extract_pdf_text

def consolidate_w2s(w2_list: list) -> dict:
    """
    Clean, deduplicate, and sum raw W-2 extraction entries by EIN.
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
                return None
        return None

    seen_employers: dict = {}

    for entry in w2_list:
        if not isinstance(entry, dict) or not entry:
            continue

        wages = parse_currency(entry.get("wages") or entry.get("gross_wages"))
        fed = parse_currency(
            entry.get("federal_withheld")
            or entry.get("federal_income_tax_withheld")
            or entry.get("federal_withholding")
        )
        if fed is None:
            tw = entry.get("tax_withheld")
            if isinstance(tw, dict):
                fed = parse_currency(tw.get("federal_income_tax") or tw.get("federal"))

        if wages is None:
            continue

        employer = (entry.get("employer") or entry.get("employer_name") or "Unknown").strip()
        taxpayer = (entry.get("taxpayer") or entry.get("employee_name") or "Unknown").strip()
        ein = (entry.get("ein") or entry.get("employer_ein") or "Unknown").strip()

        clean = {
            "taxpayer": taxpayer,
            "employer": employer,
            "ein": ein,
            "wages": wages,
            "federal_withheld": fed or 0.0,
        }

        # Deduplicate by EIN if available, else employer name
        key = ein if ein != "Unknown" else employer.lower().replace(" ", "")
        existing = seen_employers.get(key)
        if existing is None:
            seen_employers[key] = clean
        elif clean["federal_withheld"] > 0 and existing["federal_withheld"] == 0:
            seen_employers[key] = clean
        elif clean["wages"] > existing["wages"] and clean["federal_withheld"] >= existing["federal_withheld"]:
            seen_employers[key] = clean

    entries = list(seen_employers.values())
    total_wages = round(sum(e["wages"] for e in entries), 2)
    total_withheld = round(sum(e["federal_withheld"] for e in entries), 2)

    return {
        "total_w2_wages": total_wages,
        "total_federal_withheld": total_withheld,
        "entries": entries,
        "entry_count": len(entries),
    }

def _resolve_doc_type(filename: str, state: dict) -> str:
    """Look up the document type from the manifest, falling back to filename heuristics."""
    manifest_docs = state.get("manifest", {}).get("documents", [])
    for doc in manifest_docs:
        if doc.get("file") == filename:
            dtype = doc.get("type", "")
            if dtype and dtype != "UNKNOWN":
                return dtype

    # Fallback: simple filename heuristic
    name_up = filename.upper()
    if "W2" in name_up or "W-2" in name_up:
        return "W2"
    if "1099NEC" in name_up or "1099_NEC" in name_up:
        return "1099_NEC"
    if "1099DIV" in name_up or "1099_DIV" in name_up:
        return "1099_DIV"
    if "1099INT" in name_up or "1099_INT" in name_up:
        return "1099_INT"
    if "1099" in name_up:
        return "1099_OTHER"
    if "4868" in name_up or "EXTENSION" in name_up:
        return "FORM_4868"
    if "1098" in name_up or "MORTGAGE" in name_up:
        return "FORM_1098"
    if "RENTAL" in name_up or "SCHEDULE_E" in name_up:
        return "RENTAL"
    if "SCHEDULE_C" in name_up:
        return "SCHEDULE_C"
    if "PROPERTY_TAX" in name_up:
        return "PROPERTY_TAX"
    if "HSA" in name_up or "5498" in name_up:
        return "HSA"
    return "UNKNOWN"

def run_extractor(state: dict, docs_dir: Path, model: str = "gemma4:latest") -> None:
    print("\\n--- [Agent 3] Extractor Agent ---")
    queue = state.get("plan", {}).get("extraction_queue", [])
    
    # If the planner produced an empty queue, fall back to extracting every manifest doc
    if not queue:
        manifest_docs = state.get("manifest", {}).get("documents", [])
        queue = [{"file": doc["file"]} for doc in manifest_docs if doc.get("type") != "UNKNOWN"]
    
    W2_PROMPT = (
        "You are a W-2 extraction agent.\\n"
        "Extract ONLY:\\n"
        "- Box 1: Wages -> 'wages'\\n"
        "- Box 2: Federal withheld -> 'federal_withheld'\\n"
        "- Box b: Employer EIN -> 'ein'\\n"
        "- Employee name -> 'taxpayer'\\n"
        "- Employer name -> 'employer'\\n"
        "Return ONLY JSON: {'w2_wages': [{...}]}"
    )
    
    taxpayer = state.get("taxpayer", {})
    extracted_data = {
        "w2_wages": [],
        "1099s": [],
        "mortgages": [],
        "extensions": [],
        "tax_payments": [],
        "other_extracted_data": [],
        "rental_property": dict(taxpayer.get("rental_property") or {}),
        "side_business": dict(taxpayer.get("side_business") or {}),
        "filing_details": dict(taxpayer.get("filing_details") or {}),
        "taxpayer_profile": dict(taxpayer or {})
    }
    
    for item in queue:
        filename = item.get("file")
        if not filename:
            continue
            
        filepath = docs_dir / filename
        doc_type = _resolve_doc_type(filename, state)
        print(f"Extracting [{doc_type}] from: {filename}...")
        
        # Aggressively extract from all documents - no longer skipping 1099s etc.
            
        content = ""
        images = None
        if filepath.suffix.lower() == ".pdf":
            content = extract_pdf_text(filepath)
            if len(content) < 50:
                images = pdf_to_base64_images(filepath)
                content = "[Scanned/Image PDF]"
        else:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                pass
                
        system_prompt = W2_PROMPT if doc_type == "W2" else (
            "You are a tax extraction agent. Extract ALL financial data, line items, and metadata.\\n"
            "Pay special attention to any tax payments made (estimated payments, extension payments, IRS Direct Pay receipts, state vouchers).\\n"
            "Categorize your findings under the appropriate keys: 1099s, mortgages, extensions, tax_payments, rental_property, side_business, filing_details, or dump anything else into a catch-all list under the key 'other_extracted_data'.\\n"
            "Return ONLY JSON."
        )
        
        CHUNK_SIZE = 6000
        if not content:
            content = " "
        chunks = [content[i:i + CHUNK_SIZE] for i in range(0, max(1, len(content)), CHUNK_SIZE)]
        
        for i, chunk in enumerate(chunks):
            if len(chunks) > 1:
                print(f"  -> Processing chunk {i+1}/{len(chunks)}...")
                
            user_prompt = f"File name: {filename} (Part {i+1}/{len(chunks)})\\nContent:\\n{chunk}"
            try:
                # Only pass images on the first chunk to save vision processing time
                chunk_images = images if i == 0 else None
                resp = query_ollama(model, system_prompt, user_prompt, json_format=True, images=chunk_images)
                res_json = json.loads(resp)
                if doc_type == "W2" and "w2_wages" in res_json:
                    w2 = res_json["w2_wages"]
                    if isinstance(w2, list):
                        extracted_data["w2_wages"].extend(w2)
                    elif isinstance(w2, dict):
                        extracted_data["w2_wages"].append(w2)
                if "rental_property" in res_json and isinstance(res_json["rental_property"], dict):
                    extracted_data["rental_property"].update(res_json["rental_property"])
                if "side_business" in res_json and isinstance(res_json["side_business"], dict):
                    extracted_data["side_business"].update(res_json["side_business"])
                if "filing_details" in res_json and isinstance(res_json["filing_details"], dict):
                    extracted_data["filing_details"].update(res_json["filing_details"])
                    
                for arr_key in ["1099s", "mortgages", "extensions", "tax_payments", "other_extracted_data"]:
                    if arr_key in res_json:
                        val = res_json[arr_key]
                        if isinstance(val, list):
                            extracted_data[arr_key].extend(val)
                        elif isinstance(val, dict):
                            extracted_data[arr_key].append(val)
            except Exception as e:
                print(f"  [Warning] Failed to extract from {filename} chunk {i+1}: {e}")
            
    # Deduplicate W2s
    extracted_data["w2_summary"] = consolidate_w2s(extracted_data["w2_wages"])
    
    # Clean SSNs
    extracted_data = scrub_ssns(extracted_data)
    state["extracted"] = extracted_data
    state["meta"]["last_agent"] = "extractor"
