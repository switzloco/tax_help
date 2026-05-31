import os
import urllib.request
from pathlib import Path

# Target directories
BASE_DIR = Path(__file__).parent.resolve()
TEMPLATE_DIR = BASE_DIR / "final_outputs" / "templates"

# Official fillable PDF URLs
# We use standard IRS links and latest available (2024) state fillable forms.
FORM_URLS = {
    "f1040.pdf": "https://www.irs.gov/pub/irs-pdf/f1040.pdf",
    "f1040s1.pdf": "https://www.irs.gov/pub/irs-pdf/f1040s1.pdf",
    "f1040sc.pdf": "https://www.irs.gov/pub/irs-pdf/f1040sc.pdf",
    "f1040se.pdf": "https://www.irs.gov/pub/irs-pdf/f1040se.pdf",
    "f8582.pdf": "https://www.irs.gov/pub/irs-pdf/f8582.pdf",
    "f2210.pdf": "https://www.irs.gov/pub/irs-pdf/f2210.pdf",
    "ca_540nr.pdf": "https://www.ftb.ca.gov/forms/2024/2024-540nr.pdf",
    "mi_1040.pdf": "https://www.michigan.gov/taxes/-/media/Project/Websites/taxes/Forms/IIT/TY2024/MI-1040.pdf"
}

# Standard user-agent to prevent blocking by government servers
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def download_forms(force=False):
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    
    print("==================================================")
    print("Downloading Official Fillable PDF Tax Forms")
    print("==================================================")
    
    for filename, url in FORM_URLS.items():
        dest_path = TEMPLATE_DIR / filename
        if dest_path.exists() and not force:
            print(f"[Skip] {filename} already exists at {dest_path}")
            continue
            
        print(f"Downloading {filename} from {url}...")
        try:
            req = urllib.request.Request(
                url, 
                headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                with open(dest_path, "wb") as f:
                    f.write(response.read())
            print(f"  Successfully saved to {dest_path}")
        except Exception as e:
            print(f"  [ERROR] Failed to download {filename}: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Download official fillable tax form PDFs")
    parser.add_argument("--force", action="store_true", help="Force re-download of existing forms")
    args = parser.parse_args()
    
    download_forms(force=args.force)
