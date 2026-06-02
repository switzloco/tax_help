import json
import os
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, BooleanObject

def fill_pdf_form(template_path, output_path, fields_dict):
    if not template_path.exists():
        print(f"  [Warning] Template {template_path.name} not found.")
        return False
        
    try:
        reader = PdfReader(template_path)
        writer = PdfWriter()
        writer.append(reader)
        
        try:
            catalog = writer._root_object
            if "/AcroForm" in catalog:
                catalog["/AcroForm"].update({
                    NameObject("/NeedAppearances"): BooleanObject(True)
                })
        except Exception:
            pass
            
        for page in writer.pages:
            writer.update_page_form_field_values(page, fields_dict)
            
        with open(output_path, "wb") as f:
            writer.write(f)
            
        print(f"  Generated: {output_path.name}")
        return True
    except Exception as e:
        print(f"  [ERROR] Failed to fill {template_path.name}: {e}")
        return False

def main():
    workspace_dir = Path(__file__).parent.resolve()
    state_path = workspace_dir / "processed_data" / "state.json"
    template_dir = workspace_dir / "final_outputs" / "templates"
    output_dir = workspace_dir / "final_outputs" / "filled_forms"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if not state_path.exists():
        print(f"Error: {state_path} not found.")
        return
        
    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)
        
    proxy = state.get("proxy_forms", {})
    f1040 = proxy.get("f1040")
    
    if not f1040:
        print("Error: No f1040 proxy form found in state.json.")
        return

    # Basic mapping
    f1040_fields = {
        "topmostSubform[0].Page1[0].c1_2[0]": "Yes",
        "topmostSubform[0].Page1[0].f1_47[0]": f"{f1040.get('wages', 0):.2f}",
        "topmostSubform[0].Page1[0].f1_48[0]": f"{f1040.get('wages', 0):.2f}",
        "topmostSubform[0].Page1[0].f1_61[0]": f"{f1040.get('business_income', 0):.2f}",
        "topmostSubform[0].Page1[0].f1_62[0]": f"{f1040.get('adjusted_gross_income', 0):.2f}",
        "topmostSubform[0].Page1[0].f1_64[0]": f"{f1040.get('adjusted_gross_income', 0):.2f}",
        "topmostSubform[0].Page1[0].f1_65[0]": f"{f1040.get('standard_deduction', 0):.2f}",
        "topmostSubform[0].Page1[0].f1_68[0]": f"{f1040.get('taxable_income', 0):.2f}",
        "topmostSubform[0].Page2[0].f2_01[0]": f"{f1040.get('tax', 0):.2f}",
        "topmostSubform[0].Page2[0].f2_09[0]": f"{f1040.get('tax', 0):.2f}",
        "topmostSubform[0].Page2[0].f2_10[0]": f"{f1040.get('federal_withholding', 0):.2f}",
        "topmostSubform[0].Page2[0].f2_13[0]": f"{f1040.get('federal_withholding', 0):.2f}",
        "topmostSubform[0].Page2[0].f2_14[0]": f"{f1040.get('extension_payments', 0):.2f}",
        "topmostSubform[0].Page2[0].f2_21[0]": f"{f1040.get('total_payments', 0):.2f}",
        "topmostSubform[0].Page2[0].f2_31[0]": f"{f1040.get('amount_owed', 0):.2f}"
    }
    fill_pdf_form(template_dir / "f1040.pdf", output_dir / "f1040.pdf", f1040_fields)

    sch_c = proxy.get("schedule_c")
    if sch_c:
        f1040sc_fields = {
            "topmostSubform[0].Page1[0].f1_11[0]": f"{sch_c.get('gross_receipts', 0):.2f}",
            "topmostSubform[0].Page1[0].f1_17[0]": f"{sch_c.get('gross_receipts', 0):.2f}",
            "topmostSubform[0].Page1[0].f1_28[0]": f"{sch_c.get('total_expenses', 0):.2f}",
            "topmostSubform[0].Page1[0].f1_45[0]": f"{sch_c.get('net_profit_loss', 0):.2f}"
        }
        fill_pdf_form(template_dir / "f1040sc.pdf", output_dir / "f1040sc.pdf", f1040sc_fields)
        
    sch_e = proxy.get("schedule_e")
    if sch_e:
        f1040se_fields = {
            "topmostSubform[0].Page1[0].Table_Income[0].Line3[0].f1_16[0]": f"{sch_e.get('rents_received', 0):.2f}",
            "topmostSubform[0].Page1[0].Table_Expenses[0].Line18[0].f1_62[0]": f"{sch_e.get('depreciation', 0):.2f}",
            "topmostSubform[0].Page1[0].Table_Expenses[0].Line19[0].f1_65[0]": f"{sch_e.get('expenses', 0):.2f}",
            "topmostSubform[0].Page1[0].Table_Expenses[0].Line20[0].f1_68[0]": f"{sch_e.get('total_expenses', 0):.2f}",
            "topmostSubform[0].Page1[0].Table_Expenses[0].Line21[0].f1_71[0]": f"{sch_e.get('net_loss', 0):.2f}"
        }
        fill_pdf_form(template_dir / "f1040se.pdf", output_dir / "f1040se.pdf", f1040se_fields)

    f8582 = proxy.get("form_8582")
    if f8582:
        f8582_fields = {
            "topmostSubform[0].Page1[0].f1_05[0]": f"{f8582.get('rental_loss', 0):.2f}",
            "topmostSubform[0].Page1[0].f1_09[0]": f"{f8582.get('rental_loss', 0):.2f}",
            "topmostSubform[0].Page2[0].f2_125[0]": f"{f8582.get('suspended_loss', 0):.2f}"
        }
        fill_pdf_form(template_dir / "f8582.pdf", output_dir / "f8582.pdf", f8582_fields)

    print(f"All PDF tax forms successfully generated in {output_dir}")

if __name__ == "__main__":
    main()
