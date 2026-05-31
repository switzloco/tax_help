import os
from pypdf import PdfReader

def audit_pdfs(directory):
    for filename in os.listdir(directory):
        if filename.endswith(".pdf"):
            filepath = os.path.join(directory, filename)
            print(f"\n{'='*50}\nAuditing: {filename}\n{'='*50}")
            try:
                reader = PdfReader(filepath)
                fields = reader.get_fields()
                if not fields:
                    print("  No form fields found.")
                    continue
                
                count = 0
                for field_name, field_data in fields.items():
                    value = field_data.get('/V')
                    if value:
                        print(f"  {field_name}: {value}")
                        count += 1
                if count == 0:
                    print("  Form fields exist but all are empty.")
            except Exception as e:
                print(f"  Error reading {filename}: {e}")

if __name__ == "__main__":
    audit_pdfs(r"C:\Users\nswitzer\Antigrav Proj\tax_help\final_outputs\filled_forms")
