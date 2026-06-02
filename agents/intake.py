import os
import json
import shutil
from pathlib import Path
from shared.ollama_client import query_ollama
from shared.pdf_reader import extract_pdf_text

def classify_document(filename: str, content_snippet: str = "") -> str:
    name_up = filename.upper()
    snip_up = content_snippet.upper()

    if "W2" in name_up or "W-2" in name_up:
        return "W2"
    if "WAGE AND TAX STATEMENT" in snip_up or ("W-2" in snip_up and "WAGES" in snip_up):
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

def run_intake(state: dict, docs_dir: Path, model: str = "gemma4:latest") -> None:
    print("\\n--- [Agent 1] Intake Agent ---")
    files = [f for f in os.listdir(docs_dir) if f not in [".gitkeep", "taxpayer_info.json"]]
    
    manifest_docs = []
    doc_type_summary = {}
    
    system_prompt = (
        "You are an Intake Agent responsible for classifying tax files.\\n"
        "Analyze the provided filename and contents, and return a JSON object with the keys:\\n"
        "- 'document_type': (e.g., 'W2', '1099_NEC', 'Schedule_E_Rental', 'Form_4868')\\n"
        "- 'entity': (e.g., 'Spouse1', 'Spouse2', 'BusinessName', 'RentalProperty')\\n"
        "- 'suggested_filename': (format: '2025_[document_type]_[entity].[ext]')\\n"
        "Only output JSON. Do not include markdown code block formatting."
    )
    
    for filename in files:
        filepath = docs_dir / filename
        content_snippet = ""
        try:
            if filepath.suffix.lower() == ".pdf":
                content_snippet = extract_pdf_text(filepath)[:1500]
            elif filepath.suffix.lower() in [".txt", ".csv", ".json", ".md"]:
                with open(filepath, "r", encoding="utf-8") as f:
                    content_snippet = f.read(1500)
        except Exception:
            pass
                
        user_prompt = f"Filename: {filename}\\nContent snippet:\\n{content_snippet}"
        print(f"Analyzing file: {filename}...")
        
        doc_type = classify_document(filename, content_snippet)
        
        response_str = query_ollama(model, system_prompt, user_prompt, json_format=True)
        try:
            decision = json.loads(response_str)
            new_name = decision.get("suggested_filename")
            entity = decision.get("entity", "Unknown")
            if new_name and new_name != filename:
                new_filepath = docs_dir / new_name
                shutil.move(str(filepath), str(new_filepath))
                print(f"  -> Renamed {filename} to {new_name}")
                filename = new_name
                
            manifest_docs.append({
                "file": filename,
                "type": doc_type,
                "entity": entity,
                "year": state.get("meta", {}).get("tax_year", 2025),
                "status": "classified"
            })
            doc_type_summary[doc_type] = doc_type_summary.get(doc_type, 0) + 1
        except Exception as e:
            print(f"  [Warning] Failed to process {filename}: {e}")
            manifest_docs.append({
                "file": filename,
                "type": doc_type,
                "entity": "Unknown",
                "year": state.get("meta", {}).get("tax_year", 2025),
                "status": "classified_fallback"
            })
            doc_type_summary[doc_type] = doc_type_summary.get(doc_type, 0) + 1
            
    state["manifest"] = {
        "tax_year_detected": state.get("meta", {}).get("tax_year", 2025),
        "documents": manifest_docs,
        "doc_type_summary": doc_type_summary
    }
    state["meta"]["last_agent"] = "intake"
