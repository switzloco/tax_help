def calculate_federal_tax(taxable_income: float) -> float:
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

def calculate_ca_tax(taxable_income: float) -> float:
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

def calculate_late_penalties_and_interest(remaining_due: float, late_months: int = 6, interest_rate: float = 0.08, days: int = 182) -> tuple[float, float, float]:
    """Calculate late payment penalty, interest, and total balance due."""
    penalty_rate = 0.005 * late_months
    late_payment_penalty = round(remaining_due * penalty_rate, 2)
    
    interest_factor = (1 + interest_rate / 365) ** days - 1
    late_payment_interest = round(remaining_due * interest_factor, 2)
    
    total_balance_due = round(remaining_due + late_payment_penalty + late_payment_interest, 2)
    return late_payment_penalty, late_payment_interest, total_balance_due

def safe_float(val, default=0.0):
    """Safely convert any value to float."""
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
