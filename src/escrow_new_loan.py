# escrow_initial.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Dict, List
from dateutil.relativedelta import relativedelta


# ---------- Models ----------
class Frequency(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    SEMIANNUAL = "SEMIANNUAL"
    ANNUAL = "ANNUAL"

@dataclass(frozen=True)
class EscrowItem:
    name: str
    annual_amount: Decimal
    frequency: Frequency
    next_due_date: date
    payee: str

@dataclass
class ProjectionRow:
    month: date
    deposit: Decimal
    disbursements: Dict[str, Decimal]
    end_balance: Decimal

@dataclass
class AnalysisResult:
    monthly_payment: Decimal
    initial_deposit: Decimal
    cushion_required: Decimal
    annual_total: Decimal
    projection: List[ProjectionRow]


# ---------- Helpers ----------
def to_cents(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _months_between(start_month: date, n: int):
    m0 = start_month.replace(day=1)
    for i in range(n):
        yield (m0 + relativedelta(months=+i)).replace(day=1)

def _next_due_dates(item: EscrowItem, start_month: date, months=12) -> list[date]:
    freq_step = {
        Frequency.MONTHLY: 1,
        Frequency.QUARTERLY: 3,
        Frequency.SEMIANNUAL: 6,
        Frequency.ANNUAL: 12,
    }[item.frequency]
    d = item.next_due_date
    window_start = start_month.replace(day=1)
    window_end = window_start + relativedelta(months=+months)

    # roll forward into window
    while d < window_start:
        d += relativedelta(months=+freq_step)

    out = []
    while d < window_end:
        out.append(d)
        d += relativedelta(months=+freq_step)
    return out

def _build_calendar(items: list[EscrowItem], start_month: date, months=12):
    cal = {m: {} for m in _months_between(start_month, months)}
    for it in items:
        periods = {
            Frequency.MONTHLY: 12,
            Frequency.QUARTERLY: 4,
            Frequency.SEMIANNUAL: 2,
            Frequency.ANNUAL: 1,
        }[it.frequency]
        per_payment = to_cents(it.annual_amount / Decimal(periods))
        for due in _next_due_dates(it, start_month, months):
            bucket = due.replace(day=1)
            cal[bucket][it.name] = cal[bucket].get(it.name, Decimal("0.00")) + per_payment
    return cal


# ---------- Core: initial analysis ----------
def run_initial_escrow_analysis(items: list[EscrowItem], computation_month: date, cushion_policy_cap: Decimal | None = None,) -> AnalysisResult:
    start = computation_month.replace(day=1)
    annual_total = to_cents(sum((it.annual_amount for it in items), Decimal("0")))
    monthly = to_cents(annual_total / Decimal(12))

    # RESPA cushion = 1/6 of annual disbursements (never exceeded)
    respa_cap = annual_total / Decimal(6)
    cushion_allowed = to_cents(min(respa_cap, cushion_policy_cap) if cushion_policy_cap is not None else respa_cap)

    cal = _build_calendar(items, start, months=12)

    # Pass 1: project with initial_deposit = 0 to find min balance
    balance = Decimal("0.00")
    min_balance = Decimal("99999999")
    for m in _months_between(start, 12):
        disb_total = to_cents(sum(cal[m].values(), Decimal("0")))
        balance = to_cents(balance + monthly - disb_total)
        if balance < min_balance:
            min_balance = balance

    # Initial deposit needed so min_balance >= cushion
    initial_deposit = to_cents(cushion_allowed - min_balance) if min_balance < cushion_allowed else Decimal("0.00")

    # Pass 2: final projection including initial deposit at month 1
    balance = initial_deposit
    projection: List[ProjectionRow] = []
    for m in _months_between(start, 12):
        disb = {k: to_cents(v) for k, v in cal[m].items()}
        disb_total = to_cents(sum(disb.values(), Decimal("0")))
        balance = to_cents(balance + monthly - disb_total)
        projection.append(ProjectionRow(month=m, deposit=monthly, disbursements=disb, end_balance=balance))

    # Analysis Result object
    return AnalysisResult(
        monthly_payment=monthly,
        initial_deposit=initial_deposit,
        cushion_required=cushion_allowed,
        annual_total=annual_total,
        projection=projection,
    )

def _money(x):  # x is a Decimal
    return f"{x:.2f}"

def _format_disbursements(d: dict[str, "Decimal"]) -> str:
    if not d:
        return "{}"
    # Example: {Property Tax: 3000.00, Home Owners Insurance: 1200.00}
    inner = ", ".join(f"{k}: {_money(v)}" for k, v in d.items())
    return "{" + inner + "}"


# ---------- Example run (optional) ----------
if __name__ == "__main__":
    items = [
        EscrowItem(
            name="Property Tax",
            annual_amount=Decimal("6000.00"),
            frequency=Frequency.SEMIANNUAL,
            next_due_date=date(2025, 11, 15),
            payee="County Treasurer",
        ),
        EscrowItem(
            name="Home Owners Insurance",
            annual_amount=Decimal("1200.00"),
            frequency=Frequency.ANNUAL,
            next_due_date=date(2026, 6, 1),
            payee="ABC Insurance Co.",
        ),
    ]
    res = run_initial_escrow_analysis(items, date(2025, 9, 1))

    print("Monthly:", _money(res.monthly_payment))
    print("Initial deposit:", _money(res.initial_deposit))
    print("Cushion:", _money(res.cushion_required))
    print("Annual total:", _money(res.annual_total))

for r in res.projection:
    month = r.month.strftime("%Y-%m")
    monthly = _money(r.deposit)
    payments = _format_disbursements(r.disbursements)
    balance = _money(r.end_balance)
    print(f"Month: {month}  Monthly Payment: {monthly}  Payments Due: {payments}  Total Balance: {balance}")