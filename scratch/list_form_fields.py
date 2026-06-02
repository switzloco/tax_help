# /// script
# dependencies = [
#   "pypdf",
#   "cryptography",
# ]
# ///

import os
from pathlib import Path
from pypdf import PdfReader

BASE_DIR = Path(__file__).parent.parent.resolve()
TEMPLATE_DIR = BASE_DIR / "final_outputs" / "templates"

def print_ordered_fields(filename):
    pdf_path = TEMPLATE_DIR / filename
    if not pdf_path.exists():
        print(f"File {filename} not found.")
        return
        
    print(f"\n==================================================")
    print(f"Ordered Text Fields for {filename}")
    print(f"==================================================")
    
    reader = PdfReader(pdf_path)
    fields = reader.get_fields()
    
    # Sort them by their name
    for idx, name in enumerate(sorted(fields.keys())):
        field = fields[name]
        field_type = field.get("/FT", "")
        if field_type == "/Tx":
            print(f"{idx}: {name}")

if __name__ == "__main__":
    import sys
    filename = sys.argv[1] if len(sys.argv) > 1 else "f1040.pdf"
    print_ordered_fields(filename)
