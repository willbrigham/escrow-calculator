# William Brigham
# 09-07-2025

from datetime import date

# ---- date helpers ----
# return the first of the month
def first_of_month(d):
    return date(d.year, d.month, 1)

def add_months(d, n):
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, 1)

def parse_ymd(s, default=None):
    try:
        y, m, d = map(int, str(s).split("-"))
        return date(y, m, d)
    except Exception:
        return default

# ---- Build a simple 12-month schedule from a single due date + frequency ----
def add_line_to_schedule(schedule, amount, first_due, start_month, freq):
    """
    schedule: dict {1..12 -> float}
    amount: float
    first_due: date of the *next* bill
    start_month: first day of the analysis window (date)
    freq: 'annual' | 'semiannual' | 'quarterly' | 'monthly' | 'once'
    """
    if not amount or amount <= 0 or not first_due:
        return
    freq = (freq or "annual").lower()
    # Map due dates into month indices 1..12
    def maybe_add(d):
        # month index relative to start_month
        idx = (d.year - start_month.year) * 12 + (d.month - start_month.month) + 1
        if 1 <= idx <= 12:
            schedule[idx] = schedule.get(idx, 0.0) + float(amount)

    if freq in ("once", "annual"):
        maybe_add(first_of_month(first_due))
    elif freq == "semiannual":
        for off in (0, 6):
            d = add_months(first_of_month(first_due), off)
            maybe_add(d)
    elif freq == "quarterly":
        for off in (0, 3, 6, 9):
            d = add_months(first_of_month(first_due), off)
            maybe_add(d)
    elif freq == "monthly":
        # add on the first of each month, starting from first_due month or start window, whichever is later
        m0 = first_of_month(first_due)
        for i in range(12):
            d = add_months(first_of_month(start_month), i)
            if d >= m0:
                maybe_add(d)
    else:
        maybe_add(first_of_month(first_due))

# ---- Core math: smallest constant monthly deposit so balance never < -cushion ----
def required_monthly_deposit(start_balance, schedule, monthly_interest_credit, cushion_allowed):
    """
    Let balance after j months be: S0 + j*m + j*credit - cumulative_disbursements(j) >= -cushion
    => m >= (cum_disb(j) - S0 - j*credit - cushion)/j for all j >= 1
    So choose m = max(0, max_j RHS), rounded up to cents.
    """
    S0 = float(start_balance or 0.0)
    credit = float(monthly_interest_credit or 0.0)
    cushion = float(cushion_allowed or 0.0)

    cum = 0.0
    worst_needed = 0.0
    for j in range(1, 13):
        cum += float(schedule.get(j, 0.0))
        rhs = (cum - S0 - j * credit - cushion) / j
        if rhs > worst_needed:
            worst_needed = rhs
    m = max(0.0, worst_needed)
    # round *up* to cents
    m = (int(m * 100 + 0.9999)) / 100.0
    return m

def simulate_balances(S0, m, schedule, monthly_interest_credit):
    bal = float(S0 or 0.0)
    credit = float(monthly_interest_credit or 0.0)
    trail = []
    for j in range(1, 13):
        bal += m
        if credit:
            bal += credit
        bal -= float(schedule.get(j, 0.0))
        trail.append(round(bal, 2))
    return trail, (min(trail) if trail else bal)

# ---- Main entry: minimal calculator ----
def escrow_annual_minimal(record: dict) -> dict:
    """
    INPUT: record is a dict with any/all of your fields.
    This function only *uses* fields that affect the escrow math.
    Everything else is returned under 'policy_flags' for your manual refund/collection decision.
    """
    # Get the starting balance
    S0 = float(record.get("Escrow Balance"))

    # Get start date
    start = parse_ymd(record.get("Escrow Analysis Completion Date"))
    start = first_of_month(start)

    # Interest credit
    monthly_interest_credit = float(record.get("Interest on Escrow Payment Amount"))

    # Create dict for months
    schedule = {i: 0.0 for i in range(1, 13)}

    # Property tax
    tax_amt = float(record.get("Tax payee amount", record.get("Tax Payee Amount")))
    tax_due = parse_ymd(record.get("Next Tax Due Date"))
    # Added field; tax freq
    tax_freq = (record.get("Tax Frequency") or "annual")
    add_line_to_schedule(schedule, tax_amt, tax_due, start, tax_freq)

    # HAZARD (homeowner's) — include only if escrowed
    hazard_escrowed = str(record.get("Escrowed Hazard Line", "")).strip().lower() in ("1", "true", "t", "yes", "y")
    hazard_amt = float(record.get("Hazard Payee Amount", 0.0) or 0.0)
    hazard_due = parse_ymd(record.get("Next Hazard due date", record.get("Next Hazard Due Date")))
    if hazard_escrowed and hazard_amt > 0 and hazard_due:
        add_line_to_schedule(schedule, hazard_amt, hazard_due, start, "annual")

    # FLOOD / LPI — include if a dollar amount is present; use month 1 if you don't have a due date
    flood_amt = float(record.get("Flood Premiums Due", record.get("Floor Premiums Due", 0.0)) or 0.0)
    flood_due = parse_ymd(record.get("Next Flood Due Date")) or start  # simple fallback to month 1
    if flood_amt > 0:
        add_line_to_schedule(schedule, flood_amt, flood_due, start, "annual")

    # PMI — monthly until it ends (if you supply 'PMI Expected End Date')
    pmi_on = str(record.get("PMI Indicator", "")).strip().lower() in ("1", "true", "t", "yes", "y")
    pmi_monthly = float(record.get("PMI Premium Amount Monthly", 0.0) or 0.0)
    pmi_end = parse_ymd(record.get("PMI Expected End Date"))  # optional
    if pmi_on and pmi_monthly > 0:
        for j in range(1, 13):
            mdate = add_months(start, j - 1)
            if pmi_end and first_of_month(mdate) > first_of_month(pmi_end):
                break
            schedule[j] = schedule.get(j, 0.0) + pmi_monthly

    # HOA
    hoa_amt = float(record.get("HOA Amount", 0.0) or 0.0)
    hoa_due = parse_ymd(record.get("HOA Next Due Date"))
    hoa_freq = (record.get("HOA Disb Frequency") or "annual")
    if hoa_amt > 0 and hoa_due:
        add_line_to_schedule(schedule, hoa_amt, hoa_due, start, hoa_freq)

    # Sum annual disbursements
    annual_disb = round(sum(schedule.values()), 2)

    # Allowed cushion = min(policy cushion (dollars), A/6). If policy cushion missing, just use A/6.
    # NOTE: This assumes your "Escrow Cushion" field is already in dollars.
    # If it's in "months", convert before calling this function.
    policy_cushion = float(record.get("Escrow Cushion", annual_disb / 6.0) or (annual_disb / 6.0))
    allowed_cushion = round(min(policy_cushion, annual_disb / 6.0), 2)

    # Solve minimal monthly deposit m so ledger never dips below -cushion
    m = required_monthly_deposit(S0, schedule, monthly_interest_credit, allowed_cushion)

    # Project balances to get min balance, shortage/surplus
    trail, min_bal = simulate_balances(S0, m, schedule, monthly_interest_credit)
    surplus = round(max(0.0, min_bal + allowed_cushion), 2)
    shortage = round(max(0.0, -(min_bal + allowed_cushion)), 2)  # should be 0.00 given rounding-up on m

    # ---------- Return calculation + selected policy flags for your manual decision ----------
    policy_flags = {
        # Refund/collection eligibility toggles you’ll evaluate manually:
        "Delinquent Taxes Amount": record.get("Delinquint Taxes Amount") or record.get("Delinquent Taxes Amount"),
        "Bankruptcy Status": record.get("Bankruptcy Status"),
        "BK Chapter": record.get("BK Chapter"),
        "Loss Mitigation Status": record.get("Loss Mitigation Status"),
        "Foreclosure Status": record.get("Foreclosure Status"),
        "Foreclosure Sale Indicator": record.get("Foreclosure Sale Indicator"),
        "DIL Due Indicator": record.get("DIL Due Indicator"),
        "Service Release Indicator": record.get("Service Release Indicator"),
        "Escrow Cancellation": record.get("Escrow Cancellation"),
        "Escrowed Indicator": record.get("Escrowed Indicator"),
        "Escrow Waiver Indicator": record.get("Escrow Waiver Indicator"),
        "Loan Type": record.get("Loan Type"),
        "PIF Indicator": record.get("PIF Indicator"),
        # Label from prior cycle (not used for math, but handy to see):
        "Surplus/Shortage Indicator": record.get("Surplus/Shortage Indicator"),
        # State (interest/cushion rules; you may use this manually if you don’t model monthly interest above):
        "Property State": record.get("Property State"),
    }

    return {
        "loan_id": record.get("Loan ID"),
        "analysis_start": str(start),
        "annual_disbursements": annual_disb,
        "allowed_cushion": allowed_cushion,
        "new_monthly_escrow": round(m, 2),
        "min_projected_balance": round(min_bal, 2),
        "surplus": surplus,
        "shortage": shortage,
        "monthly_interest_credit": round(monthly_interest_credit, 2),
        "monthly_schedule": {m: round(v, 2) for m, v in schedule.items()},
        "month_end_balances": trail,
        "policy_flags": policy_flags,   # <-- you decide refund/collection using these
    }

 # Example input
if __name__ == "__main__":
    sample = {
        # these input fields will impact escrow calculation
        "Loan ID": "12345", # loan identifier
        "Escrow Balance": 1200.00, # start balance
        "Escrow Analysis Completion Date": "2025-09-01", # start date
        "Escrow Cushion": 500.00,  # if unknown - omit and code will use A/6
        "Interest on Escrow Payment Amount": 0.00,
        "Interest on Escrow Payment Frequency": "monthly",

        "Tax Payee Amount": 3600.00, # property tax
        "Next Tax Due Date": "2026-01-01",
        "Tax Frequency": "semiannual",  # optional; default is 'annual'; I added this field

        "Escrowed Hazard Line": "true",
        "Hazard Payee Amount": 1200.00, # home owners insurance
        "Next Hazard Due Date": "2026-05-01",

        "PMI Indicator": "true",
        "PMI Premium Amount Monthly": 75.00, # private mortgage insurance on conventional loans

        "HOA Amount": 300.00, # home owners association dues
        "HOA Disb Frequency": "annual",
        "HOA Next Due Date": "2026-03-01",

        # Flood Insurance?
        "Flood Premiums Due": 0.0,

        # Policy flags (don’t affect math)
        "Delinquent Taxes Amount": 0.0,
        "Bankruptcy Status": "None",
        "BK Chapter": None,
        "Loss Mitigation Status": "None",
        "Foreclosure Status": "None",
        "Foreclosure Sale Indicator": "No",
        "DIL Due Indicator": "No",
        "Service Release Indicator": "No",
        "Escrow Cancellation": "No",
        "Escrowed Indicator": "Yes",
        "Escrow Waiver Indicator": "No",
        "Loan Type": "Conventional", # First scenario is a conventional loan
        "PIF Indicator": "No",
        "Property State": "NY",
        "Flood Zone Indicator" : False
    }
    from pprint import pprint
    pprint(escrow_annual_minimal(sample))