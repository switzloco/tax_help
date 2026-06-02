from pathlib import Path

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

def extract_pdf_text(filepath: Path) -> str:
    """Extract text from PDF using pypdf."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(filepath))
        pdf_text = ""
        for idx, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                pdf_text += f"\\n--- Page {idx+1} ---\\n{page_text}\\n"
        content = pdf_text.strip()
        return content
    except Exception as e:
        print(f"  [Warning] pypdf extraction failed for {filepath.name}: {e}")
        return ""
