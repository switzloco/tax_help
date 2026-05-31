# /// script
# dependencies = [
#   "pypdf",
#   "cryptography",
# ]
# ///

import os
from pathlib import Path
from pypdf import PdfReader

BASE_DIR = Path(__file__).parent.resolve()
TEMPLATE_DIR = BASE_DIR / "final_outputs" / "templates"
OUTPUT_DIR = BASE_DIR / "final_outputs" / "inspected_fields"

def inspect_pdf_fields():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    print("==================================================")
    print("Inspecting Fillable PDF Tax Form Fields")
    print("==================================================")
    
    pdf_files = [f for f in os.listdir(TEMPLATE_DIR) if f.endswith(".pdf")]
    if not pdf_files:
        print(f"No PDF templates found in {TEMPLATE_DIR}. Run download_forms.py first.")
        return
        
    for filename in pdf_files:
        pdf_path = TEMPLATE_DIR / filename
        txt_path = OUTPUT_DIR / f"{pdf_path.stem}_fields.txt"
        print(f"Inspecting {filename}...")
        
        try:
            reader = PdfReader(pdf_path)
            fields = reader.get_fields()
            
            if not fields:
                print(f"  [Warning] No interactive form fields found in {filename}.")
                continue
                
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(f"Interactive fields for {filename} (Total: {len(fields)})\n")
                f.write("=" * 80 + "\n\n")
                
                # Sorted fields for easy navigation
                for name in sorted(fields.keys()):
                    field_data = fields[name]
                    field_type = field_data.get("/FT", "Unknown")
                    field_val = field_data.get("/V", "")
                    
                    # Resolve field type readability
                    type_str = "Text"
                    if field_type == "/Btn":
                        type_str = "Button/Checkbox/Radio"
                    elif field_type == "/Ch":
                        type_str = "Choice/Dropdown"
                    elif field_type == "/Sig":
                        type_str = "Signature"
                        
                    f.write(f"Field Name: {name}\n")
                    f.write(f"  Type : {type_str}\n")
                    if field_val:
                        f.write(f"  Value: {field_val}\n")
                    f.write("-" * 40 + "\n")
                    
            print(f"  Successfully wrote field list to {txt_path}")
        except Exception as e:
            print(f"  [ERROR] Failed to inspect {filename}: {e}")

if __name__ == "__main__":
    inspect_pdf_fields()
