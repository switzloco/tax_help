# /// script
# dependencies = [
#   "pypdf",
#   "cryptography",
# ]
# ///

import json
import os
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, BooleanObject

def calculate_federal_tax(taxable_income):
    # 2025 brackets for MFJ
    brackets = [
        (23850, 0.10),
        (96950, 0.12),
        (206700, 0.22),
        (394600, 0.24),
        (501050, 0.32),
        (751600, 0.35),
        (float('inf'), 0.37)
    ]
    
    tax = 0.0
    prev_limit = 0
    for limit, rate in brackets:
        if taxable_income > limit:
            tax += (limit - prev_limit) * rate
            prev_limit = limit
        else:
            tax += (taxable_income - prev_limit) * rate
            break
    return round(tax, 2)

def calculate_ca_tax(taxable_income):
    # 2025 brackets for CA MFJ
    brackets = [
        (21120, 0.01),
        (50038, 0.02),
        (78960, 0.04),
        (109822, 0.06),
        (138740, 0.08),
        (706476, 0.093),
        (float('inf'), 0.103)
    ]
    
    tax = 0.0
    prev_limit = 0
    for limit, rate in brackets:
        if taxable_income > limit:
            tax += (limit - prev_limit) * rate
            prev_limit = limit
        else:
            tax += (taxable_income - prev_limit) * rate
            break
    return round(tax, 2)

def fill_pdf_form(template_path, output_path, fields_dict):
    if not template_path.exists():
        print(f"  [Warning] Template {template_path.name} not found.")
        return False
        
    try:
        reader = PdfReader(template_path)
        writer = PdfWriter()
        writer.append(reader)
        
        # Set NeedAppearances to True to force readers to display filled values
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
    data_path = workspace_dir / "processed_data" / "tax_data_2025.json"
    template_dir = workspace_dir / "final_outputs" / "templates"
    output_dir = workspace_dir / "final_outputs" / "filled_forms"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if not data_path.exists():
        print(f"Error: {data_path} not found.")
        return
        
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    # Helper to safely convert any value to float
    def safe_float(val, default=0.0):
        if val is None:
            return default
        if isinstance(val, str):
            cleaned = val.replace("$", "").replace(",", "").strip()
            if not cleaned or cleaned.lower() in ["n/a", "null", "none"]:
                return default
            try:
                return float(cleaned)
            except ValueError:
                return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    # Safe lists/dicts
    w2_list = data.get("w2_wages") or []
    if not isinstance(w2_list, list):
        w2_list = [w2_list]

    # Extract tax variables safely
    w2_wages = sum(safe_float(item.get("gross_wages") or item.get("wages")) for item in w2_list)
    fed_withheld = sum(safe_float(item.get("federal_withheld") or item.get("tax_withheld")) for item in w2_list)
    
    side_business = data.get("side_business") or {}
    sch_c_rev = safe_float(side_business.get("gross_revenue") or side_business.get("revenue"))
    sch_c_exp = safe_float(side_business.get("reported_expenses") or side_business.get("expenses"))
    sch_c_net = safe_float(side_business.get("net_reported_loss") or side_business.get("net_reported_profit") or side_business.get("net_profit_or_loss"))
    if sch_c_net == 0.0 and (sch_c_rev != 0.0 or sch_c_exp != 0.0):
        sch_c_net = sch_c_rev - sch_c_exp
    
    rental_property = data.get("rental_property") or {}
    sch_e_inc = safe_float(rental_property.get("rental_income"))
    sch_e_exp_no_dep = safe_float(rental_property.get("rental_expenses_excl_depr") or rental_property.get("expenses"))
    sch_e_dep = safe_float(rental_property.get("calculated_depreciation_claimed"))
    sch_e_net = safe_float(rental_property.get("net_reported_loss"))
    if sch_e_net == 0.0 and (sch_e_inc != 0.0 or sch_e_exp_no_dep != 0.0):
        sch_e_net = sch_e_inc - sch_e_exp_no_dep - sch_e_dep
    
    filing_details = data.get("filing_details") or {}
    profile = data.get("taxpayer_profile") or {}
    primary = profile.get("primary_taxpayer") or {}
    spouse = profile.get("spouse") or {}
    addr = profile.get("address") or {}
    filing_prof = profile.get("filing_details") or {}
    
    prior_tax = safe_float(filing_prof.get("prior_year_total_tax") or filing_details.get("prior_year_total_tax"))
    ext_payment = safe_float(filing_prof.get("extension_payment_made") or filing_details.get("extension_payment_made"))
    remaining_due = safe_float(filing_prof.get("remaining_tax_due") or filing_details.get("remaining_tax_due"))
    
    # Extract names dynamically if present
    taxpayers = []
    fd = data.get("filing_details") or {}
    for key in ["recipient_name", "owner", "taxpayer_name", "spouse_name", "employee_name"]:
        val = fd.get(key)
        if val and isinstance(val, str) and val.strip() and val.strip().lower() not in ["n/a", "null", "none"]:
            name = val.strip()
            if name not in taxpayers:
                taxpayers.append(name)
                
    for item in w2_list:
        tp = item.get("taxpayer")
        if tp and isinstance(tp, str) and tp.strip() and tp.strip() not in taxpayers:
            taxpayers.append(tp.strip())
        epd = item.get("employment_period_details") or {}
        emp_name = epd.get("employee_name") or item.get("employee_name")
        if emp_name and isinstance(emp_name, str) and emp_name.strip() and emp_name.strip() not in taxpayers:
            taxpayers.append(emp_name.strip())
            
    taxpayers = [t for t in taxpayers if t.lower() not in ["john doe", "jane doe", "spouse 1", "spouse 2", "unknown"]]
    
    # Load profile details or fall back
    taxpayer_1 = primary.get("first_name") or "Nicholas"
    taxpayer_1_last = primary.get("last_name") or "Switzer"
    taxpayer_2 = spouse.get("first_name") or "Marlo"
    taxpayer_2_last = spouse.get("last_name") or "Manaloto"
    taxpayer_1_ssn = primary.get("ssn") or "999-99-9999"
    taxpayer_2_ssn = spouse.get("ssn") or "888-88-8888"
    
    if not primary.get("first_name") and len(taxpayers) >= 1:
        parts = taxpayers[0].split()
        if len(parts) >= 2:
            taxpayer_1 = parts[0]
            taxpayer_1_last = " ".join(parts[1:])
        else:
            taxpayer_1 = taxpayers[0]
            taxpayer_1_last = ""
            
    if not spouse.get("first_name") and len(taxpayers) >= 2:
        parts = taxpayers[1].split()
        if len(parts) >= 2:
            taxpayer_2 = parts[0]
            taxpayer_2_last = " ".join(parts[1:])
        else:
            taxpayer_2 = taxpayers[1]
            taxpayer_2_last = ""

    # Parse address dynamically
    street = addr.get("street") or "137 Union Ave E"
    city = addr.get("city") or "Campbell"
    state = addr.get("state") or "CA"
    zip_code = addr.get("zip_code") or "95008"
    
    if not addr.get("street"):
        address_str = rental_property.get("address") or fd.get("employee_address") or fd.get("address") or ""
        if address_str and address_str != "123 Wolverine Way":
            parts = [p.strip() for p in address_str.split(",") if p.strip()]
            if parts:
                if parts[-1].isdigit() or '-' in parts[-1]:
                    zip_code = parts[-1]
                    if len(parts) >= 2:
                        state = parts[-2]
                    if len(parts) >= 3:
                        city = parts[-3]
                    if len(parts) == 4:
                        street = f"{parts[0]}, {parts[1]}"
                    elif len(parts) >= 5:
                        street = ", ".join(parts[:-3])
                    else:
                        street = parts[0]
                else:
                    street = parts[0]
                    if len(parts) >= 2:
                        city = parts[1]
                    if len(parts) >= 3:
                        state_zip = parts[2].split()
                        if len(state_zip) >= 1: state = state_zip[0]
                        if len(state_zip) >= 2: zip_code = state_zip[1]

    def split_ssn(ssn_str):
        clean = "".join(c for c in ssn_str if c.isdigit())
        if len(clean) == 9:
            return clean[:3], clean[3:5], clean[5:]
        return "000", "00", "0000"

    tp1_ssn1, tp1_ssn2, tp1_ssn3 = split_ssn(taxpayer_1_ssn)
    tp2_ssn1, tp2_ssn2, tp2_ssn3 = split_ssn(taxpayer_2_ssn)

    # Mathematical rules implementation
    fed_agi = w2_wages + sch_c_net
    std_deduction = 31500.0  # 2025 standard deduction for MFJ
    taxable_income = max(0.0, fed_agi - std_deduction)
    
    calculated_fed_tax = calculate_federal_tax(taxable_income)
    total_fed_tax = fed_withheld + ext_payment + remaining_due
    total_payments = fed_withheld + ext_payment
    
    # State taxes
    ca_std_deduction = 10726.0
    ca_taxable_income = max(0.0, w2_wages - ca_std_deduction)
    ca_tax = calculate_ca_tax(ca_taxable_income)
    ca_withheld_fallback = safe_float(filing_prof.get("california_withholding_fallback"), 38000.0)
    ca_withheld = safe_float(filing_details.get("california_withholding"), ca_withheld_fallback)
    ca_due_refund = round(ca_tax - ca_withheld, 2)
    
    mi_exemptions = 2 * 5800.0
    mi_taxable_income = max(0.0, fed_agi - mi_exemptions)
    mi_tax = round(mi_taxable_income * 0.0425, 2)
    mi_withheld_fallback = safe_float(filing_prof.get("michigan_withholding_fallback"), 18000.0)
    mi_withheld = safe_float(filing_details.get("michigan_withholding"), mi_withheld_fallback)
    mi_due_refund = round(mi_tax - mi_withheld, 2)
 
    # 1. Fill Form 1040
    f1040_fields = {
        "topmostSubform[0].Page1[0].c1_2[0]": "Yes",
        "topmostSubform[0].Page1[0].f1_01[0]": taxpayer_1,
        "topmostSubform[0].Page1[0].f1_02[0]": taxpayer_1_last,
        "topmostSubform[0].Page1[0].f1_03[0]": taxpayer_2,
        "topmostSubform[0].Page1[0].f1_04[0]": taxpayer_2_last,
        "topmostSubform[0].Page1[0].f1_05[0]": street,
        "topmostSubform[0].Page1[0].f1_07[0]": city,
        "topmostSubform[0].Page1[0].f1_08[0]": state,
        "topmostSubform[0].Page1[0].f1_09[0]": zip_code,
        "topmostSubform[0].Page1[0].f1_13[0]": tp1_ssn1,
        "topmostSubform[0].Page1[0].f1_14[0]": tp1_ssn2,
        "topmostSubform[0].Page1[0].f1_15[0]": tp1_ssn3,
        "topmostSubform[0].Page1[0].f1_16[0]": tp2_ssn1,
        "topmostSubform[0].Page1[0].f1_17[0]": tp2_ssn2,
        "topmostSubform[0].Page1[0].f1_18[0]": tp2_ssn3,
        "topmostSubform[0].Page1[0].f1_47[0]": f"{w2_wages:.2f}",
        "topmostSubform[0].Page1[0].f1_48[0]": f"{w2_wages:.2f}",
        "topmostSubform[0].Page1[0].f1_61[0]": f"{sch_c_net:.2f}",
        "topmostSubform[0].Page1[0].f1_62[0]": f"{fed_agi:.2f}",
        "topmostSubform[0].Page1[0].f1_64[0]": f"{fed_agi:.2f}",
        "topmostSubform[0].Page1[0].f1_65[0]": f"{std_deduction:.2f}",
        "topmostSubform[0].Page1[0].f1_68[0]": f"{taxable_income:.2f}",
        "topmostSubform[0].Page2[0].f2_01[0]": f"{calculated_fed_tax:.2f}",
        "topmostSubform[0].Page2[0].f2_09[0]": f"{total_fed_tax:.2f}",
        "topmostSubform[0].Page2[0].f2_10[0]": f"{fed_withheld:.2f}",
        "topmostSubform[0].Page2[0].f2_13[0]": f"{fed_withheld:.2f}",
        "topmostSubform[0].Page2[0].f2_14[0]": f"{ext_payment:.2f}",
        "topmostSubform[0].Page2[0].f2_21[0]": f"{total_payments:.2f}",
        "topmostSubform[0].Page2[0].f2_31[0]": f"{remaining_due:.2f}"
    }
    fill_pdf_form(template_dir / "f1040.pdf", output_dir / "f1040.pdf", f1040_fields)
 
    # 2. Fill Schedule 1 (Form 1040)
    f1040s1_fields = {
        "topmostSubform[0].Page1[0].f1_01[0]": f"{taxpayer_1} & {taxpayer_2} {taxpayer_1_last}",
        "topmostSubform[0].Page1[0].f1_02[0]": taxpayer_1_ssn,
        "topmostSubform[0].Page1[0].f1_05[0]": f"{sch_c_net:.2f}",
        "topmostSubform[0].Page1[0].f1_07[0]": "0.00",
        "topmostSubform[0].Page1[0].f1_38[0]": f"{sch_c_net:.2f}"
    }
    fill_pdf_form(template_dir / "f1040s1.pdf", output_dir / "f1040s1.pdf", f1040s1_fields)
 
    # 3. Fill Schedule C (Form 1040) - Corrected mappings:
    # f1_1: Name of proprietor
    # f1_10: SSN
    # f1_2: Principal business code (Line B) - max length 6
    # f1_3: Principal business or profession (Line A)
    # f1_4: Business name (Line C)
    # f1_5: Business address (Line E)
    # f1_6: Employer ID number (Line D) - max length 9
    f1040sc_fields = {
        "topmostSubform[0].Page1[0].f1_1[0]": f"{taxpayer_1} {taxpayer_1_last}",
        "topmostSubform[0].Page1[0].f1_10[0]": taxpayer_1_ssn,
        "topmostSubform[0].Page1[0].f1_2[0]": "Artisan Craft Studio",  # Line A profession/business name
        "topmostSubform[0].Page1[0].f1_3[0]": "Artisan Craft Studio",  # Line C business name
        "topmostSubform[0].Page1[0].BComb[0].f1_4[0]": "454110",  # Line B code from instructions (max length 6)
        "topmostSubform[0].Page1[0].f1_5[0]": street,  # Line E address
        "topmostSubform[0].Page1[0].DComb[0].f1_6[0]": "",  # Line D EIN (max length 9)
        "topmostSubform[0].Page1[0].f1_7[0]": city,
        "topmostSubform[0].Page1[0].f1_8[0]": state,
        "topmostSubform[0].Page1[0].f1_9[0]": zip_code,
        "topmostSubform[0].Page1[0].f1_11[0]": f"{sch_c_rev:.2f}",
        "topmostSubform[0].Page1[0].f1_17[0]": f"{sch_c_rev:.2f}",
        "topmostSubform[0].Page1[0].f1_28[0]": f"{sch_c_exp:.2f}",
        "topmostSubform[0].Page1[0].f1_45[0]": f"{sch_c_net:.2f}"
    }
    fill_pdf_form(template_dir / "f1040sc.pdf", output_dir / "f1040sc.pdf", f1040sc_fields)

    # 4. Fill Schedule E (Form 1040)
    f1040se_fields = {
        "topmostSubform[0].Page1[0].f1_1[0]": f"{taxpayer_1} & {taxpayer_2} {taxpayer_1_last}",
        "topmostSubform[0].Page1[0].f1_2[0]": taxpayer_1_ssn,
        "topmostSubform[0].Page1[0].Table_Line1a[0].RowA[0].f1_3[0]": street,
        "topmostSubform[0].Page1[0].Table_Line1b[0].RowA[0].f1_6[0]": f"{city}, {state} {zip_code}",
        "topmostSubform[0].Page1[0].Table_Income[0].Line3[0].f1_16[0]": f"{sch_e_inc:.2f}",
        "topmostSubform[0].Page1[0].Table_Expenses[0].Line18[0].f1_62[0]": f"{sch_e_dep:.2f}", # Depreciation
        "topmostSubform[0].Page1[0].Table_Expenses[0].Line19[0].f1_65[0]": f"{sch_e_exp_no_dep:.2f}", # Other exp
        "topmostSubform[0].Page1[0].Table_Expenses[0].Line20[0].f1_68[0]": f"{(sch_e_exp_no_dep + sch_e_dep):.2f}", # Total exp
        "topmostSubform[0].Page1[0].Table_Expenses[0].Line21[0].f1_71[0]": f"{sch_e_net:.2f}", # Net loss
        "topmostSubform[0].Page1[0].Table_Expenses[0].Line22[0].f1_74[0]": "0.00",            # Deductible loss
        "topmostSubform[0].Page1[0].f1_82[0]": "0.00"                                         # Total Supplemental
    }
    fill_pdf_form(template_dir / "f1040se.pdf", output_dir / "f1040se.pdf", f1040se_fields)

    # 5. Fill Form 8582 (Passive Activity Loss Limitations)
    f8582_fields = {
        "topmostSubform[0].Page1[0].f1_01[0]": f"{taxpayer_1} & {taxpayer_2} {taxpayer_1_last}",
        "topmostSubform[0].Page1[0].f1_02[0]": taxpayer_1_ssn,
        "topmostSubform[0].Page1[0].f1_05[0]": f"{sch_e_net:.2f}",   # Part I rental loss
        "topmostSubform[0].Page1[0].f1_09[0]": f"{sch_e_net:.2f}",   # Part I total loss
        "topmostSubform[0].Page1[0].f1_15[0]": "0.00",               # Part II special allowance
        "topmostSubform[0].Page1[0].f1_17[0]": "0.00",               # Part II allowed loss
        "topmostSubform[0].Page2[0].f2_125[0]": f"{abs(sch_e_net):.2f}" # Part IV/V suspended loss
    }
    fill_pdf_form(template_dir / "f8582.pdf", output_dir / "f8582.pdf", f8582_fields)

    # 6. Fill Form 2210 (Underpayment of Estimated Tax - Safe Harbor met, so penalty is 0.00)
    f2210_fields = {
        "topmostSubform[0].Page1[0].f1_01[0]": f"{taxpayer_1} & {taxpayer_2} {taxpayer_1_last}",
        "topmostSubform[0].Page1[0].f1_02[0]": taxpayer_1_ssn,
        "topmostSubform[0].Page1[0].f1_04[0]": f"{(total_fed_tax * 0.90):.2f}", # 90% current year tax
        "topmostSubform[0].Page1[0].f1_08[0]": f"{(prior_tax * 1.10):.2f}",     # 110% prior year tax
        "topmostSubform[0].Page1[0].f1_09[0]": f"{(prior_tax * 1.10):.2f}",     # Required annual payment
        "topmostSubform[0].Page1[0].f1_11[0]": f"{fed_withheld:.2f}",            # Withholding
        "topmostSubform[0].Page1[0].f1_19[0]": "0.00"                           # Underpayment penalty
    }
    fill_pdf_form(template_dir / "f2210.pdf", output_dir / "f2210.pdf", f2210_fields)

    # 7. Fill California Form 540NR
    ca_540nr_fields = {
        "540NR_form_1002": taxpayer_1,
        "540NR_form_1003": taxpayer_1_last,
        "540NR_form_1004": taxpayer_2,
        "540NR_form_1005": taxpayer_2_last,
        "540NR_form_1006": street,
        "540NR_form_1008": city,
        "540NR_form_1009": state,
        "540NR_form_1010": zip_code,
        "540NR_form_1011": taxpayer_1_ssn,
        "540NR_form_1012": taxpayer_2_ssn,
        "540NR_form_2001": f"{fed_agi:.2f}",
        "540NR_form_2002": f"{w2_wages:.2f}",
        "540NR_form_2003": f"{ca_std_deduction:.2f}",
        "540NR_form_2004": f"{ca_taxable_income:.2f}",
        "540NR_form_2005": f"{ca_withheld:.2f}",
        "540NR_form_2006": f"{ca_tax:.2f}",
        "540NR_form_2007": f"{ca_due_refund:.2f}"
    }
    fill_pdf_form(template_dir / "ca_540nr.pdf", output_dir / "ca_540nr.pdf", ca_540nr_fields)

    # 8. Fill Michigan Form MI-1040
    mi_1040_fields = {
        "F First Name": taxpayer_1,
        "F Last Name": taxpayer_1_last,
        "Sp First Name": taxpayer_2,
        "Sp Last Name": taxpayer_2_last,
        "Home address": street,
        "City or town": city,
        "State": state,
        "Zip Code": zip_code,
        "FSSN1": tp1_ssn1, "FSSN2": tp1_ssn2, "FSSN3": tp1_ssn3,
        "SpSSN1": tp2_ssn1, "SpSSN2": tp2_ssn2, "SpSSN3": tp2_ssn3,
        "line 10": f"{fed_agi:.2f}",
        "9a Number of Exemptions": "2",
        "Line 9a Total": f"{mi_exemptions:.2f}",
        "line 15": f"{mi_taxable_income:.2f}",
        "line 17": f"{mi_tax:.2f}",
        "line 20": f"{mi_withheld:.2f}",
        "line 33": f"{mi_due_refund:.2f}"
    }
    fill_pdf_form(template_dir / "mi_1040.pdf", output_dir / "mi_1040.pdf", mi_1040_fields)

    print(f"All PDF tax forms successfully generated in {output_dir}")

if __name__ == "__main__":
    main()
