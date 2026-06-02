from shared.tax_math import calculate_federal_tax, calculate_ca_tax, safe_float

def run_form_proxy(state: dict) -> None:
    print("\\n--- [Agent 5] Form Proxy Agent ---")
    extracted = state.get("extracted", {})
    
    # 1. Gather all data
    w2_summary = extracted.get("w2_summary", {})
    w2_wages = safe_float(w2_summary.get("total_w2_wages"), 0.0)
    fed_withheld = safe_float(w2_summary.get("total_federal_withheld"), 0.0)
    
    side_biz = extracted.get("side_business", {})
    sch_c_rev = safe_float(side_biz.get("gross_revenue") or side_biz.get("revenue"), 0.0)
    sch_c_exp = safe_float(side_biz.get("reported_expenses") or side_biz.get("expenses"), 0.0)
    sch_c_net = safe_float(side_biz.get("net_reported_loss") or side_biz.get("net_reported_profit") or side_biz.get("net_profit_or_loss"), 0.0)
    if sch_c_net == 0.0 and (sch_c_rev != 0.0 or sch_c_exp != 0.0):
        sch_c_net = sch_c_rev - sch_c_exp
        
    rental = extracted.get("rental_property", {})
    sch_e_inc = safe_float(rental.get("rental_income"), 0.0)
    sch_e_exp_no_dep = safe_float(rental.get("rental_expenses_excl_depr") or rental.get("expenses"), 0.0)
    sch_e_dep = safe_float(rental.get("calculated_depreciation_claimed"), 0.0)
    sch_e_net = safe_float(rental.get("net_reported_loss"), 0.0)
    if sch_e_net == 0.0 and (sch_e_inc != 0.0 or sch_e_exp_no_dep != 0.0):
        sch_e_net = sch_e_inc - sch_e_exp_no_dep - sch_e_dep
        
    filing = extracted.get("filing_details", {})
    prior_tax = safe_float(filing.get("prior_year_total_tax"), 0.0)
    ext_payment = safe_float(filing.get("extension_payment_made"), 0.0)
    
    # 2. Compute Federal Math (assuming MFJ)
    fed_agi = w2_wages + sch_c_net
    std_deduction = 31500.0
    taxable_income = max(0.0, fed_agi - std_deduction)
    
    calculated_fed_tax = calculate_federal_tax(taxable_income)
    total_payments = fed_withheld + ext_payment
    amount_owed = max(0.0, calculated_fed_tax - total_payments)
    
    # 3. Create JSON Proxy Forms
    proxy_forms = {
        "f1040": {
            "wages": w2_wages,
            "business_income": sch_c_net,
            "adjusted_gross_income": fed_agi,
            "standard_deduction": std_deduction,
            "taxable_income": taxable_income,
            "tax": calculated_fed_tax,
            "federal_withholding": fed_withheld,
            "extension_payments": ext_payment,
            "total_payments": total_payments,
            "amount_owed": amount_owed
        },
        "schedule_c": None,
        "schedule_e": None,
        "form_8582": None
    }
    
    if sch_c_rev != 0 or sch_c_exp != 0 or sch_c_net != 0:
        proxy_forms["schedule_c"] = {
            "gross_receipts": sch_c_rev,
            "total_expenses": sch_c_exp,
            "net_profit_loss": sch_c_net
        }
        
    if sch_e_inc != 0 or sch_e_exp_no_dep != 0 or sch_e_net != 0:
        proxy_forms["schedule_e"] = {
            "rents_received": sch_e_inc,
            "expenses": sch_e_exp_no_dep,
            "depreciation": sch_e_dep,
            "total_expenses": sch_e_exp_no_dep + sch_e_dep,
            "net_loss": sch_e_net
        }
        proxy_forms["form_8582"] = {
            "rental_loss": sch_e_net,
            "suspended_loss": abs(sch_e_net)
        }
        
    state["proxy_forms"] = proxy_forms
    state["meta"]["last_agent"] = "form_proxy"
