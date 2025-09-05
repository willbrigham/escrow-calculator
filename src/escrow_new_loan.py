from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional, Dict, Tuple
import math

@dataclass
class Disbursement:
    kind: str                 # 'tax', 'hazard', 'flood', 'pmi', 'hoa', etc.
    amount: float
    due_date: date            # first due date inside the 12-mo window
    frequency: str = "annual" # 'annual','semiannual','quarterly','monthly','once'
    # Generate the next 12 months of instances based on frequency:
    def expand(self, start: date, months: int = 12) -> List[Tuple[int, float]]:
        """Return [(month_index_1_to_12, amount), ...] for due dates within the 12-mo window starting at 'start'."""
        out = []
        # Helper to add if inside window
        def add_if_in_window(d: date):
            if 0 <= (d.year - start.year)*12 + (d.month - start.month) < months:
                idx = (d.year - start.year)*12 + (d.month - start.month) + 1
                out.append((idx, self.amount))
        # Frequency expansion:
        d = self.due_date
        if self.frequency == "monthly":
            # Add at due_date month index, then each month same day (best-effort)
            cur = date(start.year, start.month, 1)
            # Align to first of month for simplicity; in production, align to bill cycle day.
            for i in range(months):
                mdate = date(cur.year, cur.month, 1)
                if mdate >= date(d.year, d.month, 1):
                    add_if_in_window(mdate)
                # step
                month = cur.month + 1
                year = cur.year + (month - 1)//12
                month = ((month - 1) % 12) + 1
                cur = date(year, month, 1)
        elif self.frequency in {"annual","once"}:
            add_if_in_window(date(self.due_date.year, self.due_date.month, 1))
        elif self.frequency == "semiannual":
            for off in (0, 6):
                m = (self.due_date.month - 1 + off) % 12 + 1
                y = self.due_date.year + (self.due_date.month - 1 + off)//12
                add_if_in_window(date(y, m, 1))
        elif self.frequency == "quarterly":
            for off in (0, 3, 6, 9):
                m = (self.due_date.month - 1 + off) % 12 + 1
                y = self.due_date.year + (self.due_date.month - 1 + off)//12
                add_if_in_window(date(y, m, 1))
        else:
            # default: treat as once
            add_if_in_window(date(self.due_date.year, self.due_date.month, 1))
        return out

@dataclass
class LoanEscrowInput:
    loan_id: str
    analysis_start: date
    escrow_balance: float
    escrow_cushion_policy: float  # e.g., 2 months equivalent, but we will cap at A/6
    state_pays_interest: bool
    interest_on_escrow_amount: float = 0.0  # monthly credit if applicable
    is_current_for_refund: bool = True
    waiver_indicator: bool = False
    delinquent: bool = False
    bankruptcy: bool = False
    foreclosure: bool = False
    service_release_pending: bool = False
    # PMI handling
    pmi_indicator: bool = False
    pmi_monthly: float = 0.0
    pmi_expected_end: Optional[date] = None
    # Disbursement lines supplied externally:
    lines: List[Disbursement] = field(default_factory=list)

@dataclass
class EscrowResult:
    annual_disbursements: float
    allowed_cushion: float
    new_monthly_escrow: float
    projected_min_balance: float
    shortage: float
    surplus: float
    shortage_collection_months: int
    refund_action: str         # 'refund', 'credit', 'hold'
    notes: List[str]

def build_12mo_schedule(inp: LoanEscrowInput) -> Dict[int, float]:
    """Return {month_index(1..12): total_disbursement}."""
    sched: Dict[int, float] = {i: 0.0 for i in range(1, 13)}
    # Expand core lines
    for d in inp.lines:
        for idx, amt in d.expand(inp.analysis_start, months=12):
            sched[idx] += amt
    # Add PMI if active and within window
    if inp.pmi_indicator and inp.pmi_monthly > 0:
        for m in range(1, 13):
            m_date = add_months(first_of_month(inp.analysis_start), m-1)
            if inp.pmi_expected_end and first_of_month(m_date) > first_of_month(inp.pmi_expected_end):
                break
            sched[m] += inp.pmi_monthly
    return sched

def first_of_month(d: date) -> date:
    return date(d.year, d.month, 1)

def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = (m % 12) + 1
    return date(y, m, 1)

def simulate_running_balance(S0: float, m: float, sched: Dict[int, float], monthly_interest_credit: float, cushion: float) -> Tuple[float, List[float]]:
    """Return (min_balance, balances_by_month_end). Balance threshold is -cushion."""
    bal = S0
    mins = []
    for i in range(1, 13):
        bal += m
        if monthly_interest_credit:
            bal += monthly_interest_credit
        bal -= sched.get(i, 0.0)
        mins.append(bal)
    return (min(mins) if mins else S0, mins)

def find_required_monthly_payment(S0: float, sched: Dict[int, float], monthly_interest_credit: float, cushion: float) -> float:
    """Binary search smallest m so min balance >= -cushion."""
    A = sum(sched.values())
    lo = A/12.0  # base line
    hi = lo + max(2000.0, A)  # a safe upper bound; tighten for production
    for _ in range(40):
        mid = (lo + hi) / 2.0
        min_bal, _ = simulate_running_balance(S0, mid, sched, monthly_interest_credit, cushion)
        if min_bal >= -cushion:
            hi = mid
        else:
            lo = mid
    return round(hi, 2)

def analyze_escrow(inp: LoanEscrowInput) -> EscrowResult:
    sched = build_12mo_schedule(inp)
    A = sum(sched.values())
    # RESPA cap: 1/6 of annual disbursements
    legal_cushion_cap = A / 6.0
    allowed_cushion = round(min(inp.escrow_cushion_policy, legal_cushion_cap), 2)

    # Solve for new monthly escrow
    m_new = find_required_monthly_payment(
        S0=inp.escrow_balance,
        sched=sched,
        monthly_interest_credit=(inp.interest_on_escrow_amount if inp.state_pays_interest else 0.0),
        cushion=allowed_cushion
    )

    # Compute min with the *new* payment to measure shortage/surplus at analysis
    min_bal, trail = simulate_running_balance(
        S0=inp.escrow_balance,
        m=m_new,
        sched=sched,
        monthly_interest_credit=(inp.interest_on_escrow_amount if inp.state_pays_interest else 0.0),
        cushion=allowed_cushion
    )

    # If min_bal < -cushion, you have a deficiency; binary search guarantees no, but we keep logic general.
    deficiency = max(0.0, (-allowed_cushion) - min_bal)

    # Using the new payment, the difference between min_bal and -cushion indicates surplus(+)/shortage(-) at settle-up.
    # If min_bal > -cushion, that excess will remain at the lowest point; treat as surplus.
    surplus = max(0.0, min_bal + allowed_cushion)
    shortage = 0.0 if surplus > 0 else deficiency

    # Policy on actions
    refund_action = "refund"
    if not inp.is_current_for_refund or inp.delinquent or inp.bankruptcy or inp.foreclosure or inp.service_release_pending:
        refund_action = "credit"
    if surplus <= 50.00:  # RESPA $50 threshold
        refund_action = "credit"

    # Shortage collection months (FNMA conventional: 12 by default)
    shortage_months = 12

    notes = []
    if inp.state_pays_interest:
        notes.append("State requires interest on escrow; modeled as monthly credit.")
    if inp.pmi_indicator and inp.pmi_expected_end:
        notes.append(f"PMI ends {inp.pmi_expected_end}; PMI included only until that month.")
    if refund_action != "refund":
        notes.append("Surplus not refunded due to status/threshold; credited to account per policy.")

    return EscrowResult(
        annual_disbursements=round(A, 2),
        allowed_cushion=allowed_cushion,
        new_monthly_escrow=m_new,
        projected_min_balance=round(min_bal, 2),
        shortage=round(shortage, 2),
        surplus=round(surplus, 2),
        shortage_collection_months=shortage_months,
        refund_action=refund_action,
        notes=notes
    )