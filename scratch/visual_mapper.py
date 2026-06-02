# /// script
# dependencies = [
#   "pypdf",
#   "cryptography",
# ]
# ///

import os
from pathlib import Path
from pypdf import PdfReader, PdfWriter

BASE_DIR = Path(__file__).parent.parent.resolve()  # tax_help root
TEMPLATE_DIR = BASE_DIR / "final_outputs" / "templates"
MAPS_DIR = BASE_DIR / "final_outputs" / "visual_maps"

def create_visual_maps():
    MAPS_DIR.mkdir(parents=True, exist_ok=True)
    
    print("==================================================")
    print("Creating Visual Field Maps for PDF Forms")
    print("==================================================")
    
    pdf_files = [f for f in os.listdir(TEMPLATE_DIR) if f.endswith(".pdf")]
    if not pdf_files:
        print(f"No PDF templates found in {TEMPLATE_DIR}.")
        return
        
    for filename in pdf_files:
        pdf_path = TEMPLATE_DIR / filename
        out_path = MAPS_DIR / f"mapped_{filename}"
        print(f"Mapping {filename}...")
        
        try:
            reader = PdfReader(pdf_path)
            writer = PdfWriter()
            writer.append(reader)
            
            fields = reader.get_fields()
            if not fields:
                print(f"  No fields found in {filename}")
                continue
                
            # Dictionary of fields to update on each page
            # pypdf allows updating fields by calling update_page_form_field_values on a page
            for page_idx, page in enumerate(writer.pages):
                fields_to_fill = {}
                for name, field in fields.items():
                    # We only fill text fields (not checkboxes, which start with '/Btn')
                    field_type = field.get("/FT", "")
                    if field_type == "/Text":
                        # We use the short name of the field (last part) to fit in the box
                        short_name = name.split(".")[-1]
                        # Trim if it's too long
                        if len(short_name) > 15:
                            short_name = short_name[-15:]
                        fields_to_fill[name] = short_name
                
                if fields_to_fill:
                    writer.update_page_form_field_values(page, fields_to_fill)
            
            with open(out_path, "wb") as f:
                writer.write(f)
            print(f"  Saved visual map to {out_path}")
            
        except Exception as e:
            print(f"  [ERROR] Failed to map {filename}: {e}")

if __name__ == "__main__":
    create_visual_maps()
