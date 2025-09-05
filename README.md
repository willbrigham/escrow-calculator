# Escrow Analysis

Will be testing 8 different escrow features.

1. Initial escrow analysis (new loan setup)
2. annual escrow analysis - no significant changes 
3. escrow anlysis with tax increase - shortage scenario 
4. escrow anlysis with tax/insurance decrease - surplus scenario
5. short year escrow analysis (scrow computation year change) 
6. cancel/rescind pror escrow anlysis 
7. escrow analysis by loan type and investor-specific requirements 
8. accuracy verification & parallel run comparison next step initial escrow analysis

## Escrow definitions

Mortgage escrow / impound account (ongoing): After you get the mortgage, your servicer keeps a small account in your name. You pay into it every month and the servicer uses it to pay recurring bills tied to the property—like property taxes, homeowners insurance, sometimes flood insurance, mortgage insurance, HOA dues, etc. It runs for years, not once.

## How the Code Works

1) What actually drives the escrow math

These fields determine the 12-month disbursement schedule and the payment you need:

Disbursement amounts & timing
• Tax payee amount + Next Tax Due Date (may be 1–4 installments; represent as dated line items)
• Hazard Payee Amount + Next Hazard Due Date (usually annual)
• Flood / SFHA & Force-Placed Policy Indicators + Flood Premiums Due + Next Due Date (if applicable)
• PMI Indicator + PMI Premium Amount Monthly (+ expected end date based on cancellation rules; if PMI ends mid-year, only include until the cancellation month)
• HOA Amount + HOA Next Due Date + HOA Disb Frequency
• (Optional credits) Interest on Escrow Payment Amount/Frequency (some states require paying interest to the borrower—model as a monthly credit into the escrow ledger if applicable)

Current balance, cushion, and cadence
• Escrow Balance (starting S₀)
• Escrow Cushion (policy cap, but the legal max is 1/6 of projected annual disbursements)
• Escrow Analysis Completion Date (sets your 12-month projection window start)
• Escrow Spread Calculator / Escrow Spread Term (how you spread shortage; usually 12 months for FNMA conventional)

Conceptually:

Build a dated list of all disbursements over the next 12 months.

Sum them for A = total annual disbursements.

Allowed cushion C = min(policy cushion, A/6).

Find the minimum monthly escrow deposit m such that the projected running balance over 12 months never dips below −C.

Compare the borrower’s current starting balance and timing to determine shortage/surplus and apply RESPA/FNMA rules to collect/refund.

2) What affects eligibility/rules (but not the raw math)

These flip refund/collection switches and may alter whether you include certain lines:

Refund/collection eligibility
• Delinquency / Foreclosure Status / Bankruptcy Status & BK Chapter / Loss Mitigation Status
– If not current (e.g., delinquent, in BK/FC), you typically do not cut a surplus refund check; you credit it to the account.
– Shortage/deficiency may be collected over 12 months (or faster under some policies), but some loss-mit programs can override.
• Service Release Indicator (if a transfer of servicing is imminent, some servicers avoid cash refunds)
• Escrow Waiver Indicator (if waived, you may halt future deposits after a settle-up)
• PIF (Paid in Full), DIL (Deed-in-Lieu), Foreclosure Sale Indicator ⇒ special handling; you don’t run standard annual collection.

Which lines exist
• SFHA/Flood Zone Indicator + Force Placed Policy Indicators + Cancelled LPI Indicator (controls whether to include flood/LPI premiums)
• VA Loss Claims / VA Loss Claim fields (not typical for conventional, but if present ⇒ special servicing logic, usually not a standard FNMA conventional)
• PMI Indicator + Original LTV (helps decide if/when PMI cancels inside the 12-month window)

Admin / audit
• 45 Day Letter Cycle (governs LPI compliance, not core math)
• Escrow Cancellation (closing escrow going forward? Then do a final settle-up only)
• Loan Type (conventional/FNMA here)
• Property State (state interest on escrow rules; whether interest is owed to borrower and affects the ledger as a credit)

3) A practical, auditable algorithm

Use a projection ledger. Each row = month i (1..12) with:

starting balance

deposit m (unknown at first)

interest credit (if applicable)

− disbursements due that month (tax/hazard/flood/PMI/HOA)

ending balance

We choose m so that the minimum ending balance across the projection ≥ −C (i.e., the account never goes below the cushion).

A robust way to determine m is to binary-search the smallest m that satisfies the constraint (fast, simple, auditable). Then compute shortage/surplus versus the allowed cushion.

Key business rules to encode

Cushion: maximum allowed by RESPA is 1/6 of A (two months). If your “Escrow Cushion” field is higher, cap it at A/6. If the policy is stricter (some states), use the stricter one.

Surplus: if projected surplus > $50 and the loan is current, refund; otherwise credit to next year’s payments.

Shortage: spread over 12 months by default for FNMA conventional.

Deficiency (balance goes negative beyond cushion using the current monthly deposit): collect faster per policy (often 2–12 months).

Interest on escrow (state-specific): if owed monthly, treat as a monthly credit to the ledger (reduces required m slightly).

PMI ending mid-cycle: include only until expected cancellation month.

Force-placed (LPI): if active, include that premium until cancelled.

Waived escrow: after settle-up, you typically stop collecting (depends on policy setting).