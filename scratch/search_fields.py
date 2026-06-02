import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.resolve()
INSPECT_DIR = BASE_DIR / "final_outputs" / "inspected_fields"

def search_fields(pattern, filename):
    filepath = INSPECT_DIR / filename
    if not filepath.exists():
        print(f"File {filename} not found.")
        return
        
    print(f"\n--- Matches for '{pattern}' in {filename} ---")
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
        
    blocks = content.split("----------------------------------------")
    for block in blocks:
        if pattern.lower() in block.lower():
            print(block.strip())
            print("-" * 40)

if __name__ == "__main__":
    import sys
    pattern = sys.argv[1] if len(sys.argv) > 1 else "f1_"
    filename = sys.argv[2] if len(sys.argv) > 2 else "f1040_fields.txt"
    search_fields(pattern, filename)
