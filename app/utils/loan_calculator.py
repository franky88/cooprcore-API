from datetime import datetime, date
from dateutil.relativedelta import relativedelta

from . import utcnow


# ------------------------------------------------------------------ #
# Loan type configuration — used as fallback if settings unavailable
# ------------------------------------------------------------------ #

LOAN_TYPE_CONFIG: dict[str, dict] = {
    "Multi-Purpose": {"annual_rate": 12.0, "max_term_months": 36},
    "Emergency":     {"annual_rate": 10.0, "max_term_months": 12},
    "Business":      {"annual_rate": 14.0, "max_term_months": 48},
    "Salary":        {"annual_rate":  8.0, "max_term_months":  6},
    "Housing":       {"annual_rate": 10.0, "max_term_months": 60},
    "Educational":   {"annual_rate":  8.0, "max_term_months": 24},
}

LOAN_TYPES = list(LOAN_TYPE_CONFIG.keys())

LOAN_MIN_MEMBERSHIP_MONTHS: dict[str, int] = {
    "Emergency": 3,
}
LOAN_DEFAULT_MIN_MEMBERSHIP_MONTHS = 6

COMAKER_THRESHOLD = 30_000.0
MAX_ACTIVE_LOANS = 2
DAILY_PENALTY_RATE = 0.03 / 30


# ------------------------------------------------------------------ #
# Dynamic config reader — reads from DB, falls back to constants above
# ------------------------------------------------------------------ #

def get_effective_loan_config() -> dict[str, dict]:
    try:
        from ..extensions import mongo

        settings = mongo.db.settings.find_one({"key": "global"}) or {}
        loan_rates = settings.get("loan_rates") or {}

        if not loan_rates:
            return LOAN_TYPE_CONFIG

        config = {}
        for loan_type, fallback in LOAN_TYPE_CONFIG.items():
            type_settings = loan_rates.get(loan_type, {})
            config[loan_type] = {
                "annual_rate": float(
                    type_settings.get("rate", fallback["annual_rate"])
                ),
                "max_term_months": int(
                    type_settings.get("max_term", fallback["max_term_months"])
                ),
            }
        return config

    except Exception:
        return LOAN_TYPE_CONFIG


def get_effective_settings() -> dict:
    try:
        from ..extensions import mongo

        settings = mongo.db.settings.find_one({"key": "global"}) or {}
        return {
            "comaker_threshold": float(
                settings.get("comaker_threshold", COMAKER_THRESHOLD)
            ),
            "max_active_loans": int(
                settings.get("max_active_loans", MAX_ACTIVE_LOANS)
            ),
            "penalty_rate_monthly": float(
                settings.get("penalty_rate_monthly", 3.0)
            ),
        }
    except Exception:
        return {
            "comaker_threshold": COMAKER_THRESHOLD,
            "max_active_loans": MAX_ACTIVE_LOANS,
            "penalty_rate_monthly": 3.0,
        }


# ------------------------------------------------------------------ #
# Core amortization computation
# ------------------------------------------------------------------ #

def compute_amortization(
    principal: float,
    annual_rate: float,
    term_months: int,
    release_date: datetime | None = None,
) -> dict:
    monthly_rate = annual_rate / 100 / 12

    if monthly_rate == 0:
        monthly_amortization = principal / term_months
    else:
        monthly_amortization = (
            principal
            * (monthly_rate * (1 + monthly_rate) ** term_months)
            / ((1 + monthly_rate) ** term_months - 1)
        )

    total_payable = monthly_amortization * term_months
    total_interest = total_payable - principal

    schedule = []
    balance = principal

    for period in range(1, term_months + 1):
        interest_portion = balance * monthly_rate
        principal_portion = monthly_amortization - interest_portion
        balance -= principal_portion

        row = {
            "period": period,
            "payment": round(monthly_amortization, 2),
            "principal": round(principal_portion, 2),
            "interest": round(interest_portion, 2),
            "balance": round(max(balance, 0), 2),
        }

        if release_date is not None:
            row["due_date"] = (
                release_date + relativedelta(months=period)
            ).replace(hour=0, minute=0, second=0, microsecond=0)

        schedule.append(row)

    return {
        "monthly_amortization": round(monthly_amortization, 2),
        "total_payable": round(total_payable, 2),
        "total_interest": round(total_interest, 2),
        "schedule": schedule,
    }


# ------------------------------------------------------------------ #
# Maturity date
# ------------------------------------------------------------------ #

def compute_maturity_date(release_date: datetime, term_months: int) -> datetime:
    return release_date + relativedelta(months=term_months)


# ------------------------------------------------------------------ #
# Penalty
# ------------------------------------------------------------------ #

def compute_penalty(amount_due: float, days_late: int, daily_rate: float = DAILY_PENALTY_RATE) -> float:
    if days_late <= 0 or amount_due <= 0:
        return 0.0
    return round(amount_due * daily_rate * days_late, 2)


# ------------------------------------------------------------------ #
# Payment allocation
# ------------------------------------------------------------------ #

def allocate_payment(
    amount_paid: float,
    penalty_due: float,
    interest_due: float,
    principal_due: float,
) -> dict:
    remaining = round(amount_paid, 2)

    penalty_portion = min(remaining, round(penalty_due, 2))
    remaining = round(remaining - penalty_portion, 2)

    interest_portion = min(remaining, round(interest_due, 2))
    remaining = round(remaining - interest_portion, 2)

    principal_portion = min(remaining, round(principal_due, 2))
    remaining = round(remaining - principal_portion, 2)

    excess = max(round(remaining, 2), 0.0)

    return {
        "penalty_portion": round(penalty_portion, 2),
        "interest_portion": round(interest_portion, 2),
        "principal_portion": round(principal_portion, 2),
        "excess": round(excess, 2),
    }


# ------------------------------------------------------------------ #
# Membership eligibility check helper
# ------------------------------------------------------------------ #

def months_since(past_date: datetime) -> int:
    now = utcnow()
    delta = relativedelta(now, past_date)
    return delta.years * 12 + delta.months


# ------------------------------------------------------------------ #
# Payment-state helpers
# ------------------------------------------------------------------ #

def _sum_paid_components(payments: list[dict]) -> dict:
    principal_paid = round(sum(float(p.get("principal_portion", 0) or 0) for p in payments), 2)
    interest_paid = round(sum(float(p.get("interest_portion", 0) or 0) for p in payments), 2)
    penalty_paid = round(sum(float(p.get("penalty_portion", 0) or 0) for p in payments), 2)

    return {
        "principal_paid": principal_paid,
        "interest_paid": interest_paid,
        "penalty_paid": penalty_paid,
        "applied_to_schedule": round(principal_paid + interest_paid, 2),
    }


def _first_unpaid_installment(schedule: list[dict], principal_paid: float, interest_paid: float) -> dict | None:
    remaining_principal_paid = round(principal_paid, 2)
    remaining_interest_paid = round(interest_paid, 2)

    for item in schedule:
        applied_interest = min(remaining_interest_paid, item["interest"])
        remaining_interest_paid = round(remaining_interest_paid - applied_interest, 2)

        applied_principal = min(remaining_principal_paid, item["principal"])
        remaining_principal_paid = round(remaining_principal_paid - applied_principal, 2)

        interest_remaining = round(item["interest"] - applied_interest, 2)
        principal_remaining = round(item["principal"] - applied_principal, 2)

        if interest_remaining > 0 or principal_remaining > 0:
            return {
                "period": item["period"],
                "due_date": item.get("due_date"),
                "interest_due": max(interest_remaining, 0.0),
                "principal_due": max(principal_remaining, 0.0),
                "payment_due": round(max(interest_remaining, 0.0) + max(principal_remaining, 0.0), 2),
            }

    return None


def compute_payment_state(
    loan: dict,
    prior_payments: list[dict],
    as_of: datetime,
    penalty_rate_daily: float,
) -> dict:
    """
    Reconstruct the real due state of the loan as of `as_of`.

    Rules:
    - Uses scheduled installments, not raw current balance math.
    - Computes due interest/principal only for installments already due.
    - If nothing is due yet, returns the next unpaid installment as advance due.
    - Penalty accrues only on overdue unpaid scheduled installment amounts.
    """
    release_date = loan.get("date_released")
    if release_date is None:
        # Fallback — should rarely happen because only Current/Past Due loans can be paid.
        outstanding_balance = round(float(loan.get("outstanding_balance", loan["principal"])), 2)
        monthly_rate = float(loan["interest_rate"]) / 100 / 12
        interest_due = round(outstanding_balance * monthly_rate, 2)
        principal_due = round(min(float(loan["monthly_amortization"]) - interest_due, outstanding_balance), 2)

        return {
            "outstanding_balance": outstanding_balance,
            "interest_due": max(interest_due, 0.0),
            "principal_due": max(principal_due, 0.0),
            "penalty_due": 0.0,
            "due_installments": 0,
            "overdue_installments": 0,
            "next_due_date": None,
        }

    amort = compute_amortization(
        principal=float(loan["principal"]),
        annual_rate=float(loan["interest_rate"]),
        term_months=int(loan["term_months"]),
        release_date=release_date,
    )
    schedule = amort["schedule"]

    paid = _sum_paid_components(prior_payments)
    principal_paid = paid["principal_paid"]
    interest_paid = paid["interest_paid"]
    penalty_paid = paid["penalty_paid"]
    applied_to_schedule = paid["applied_to_schedule"]

    outstanding_balance = round(max(float(loan["principal"]) - principal_paid, 0.0), 2)

    # Scheduled amounts that are already due as of payment date
    due_items = [
        item for item in schedule
        if item.get("due_date") is not None and item["due_date"] <= as_of
    ]
    overdue_items = [
        item for item in schedule
        if item.get("due_date") is not None and item["due_date"] < as_of
    ]

    total_due_interest = round(sum(item["interest"] for item in due_items), 2)
    total_due_principal = round(sum(item["principal"] for item in due_items), 2)

    scheduled_interest_due = round(max(total_due_interest - interest_paid, 0.0), 2)
    scheduled_principal_due = round(max(total_due_principal - principal_paid, 0.0), 2)

    # If no installment is due yet, allow advance payment against the next unpaid installment
    if scheduled_interest_due <= 0 and scheduled_principal_due <= 0 and outstanding_balance > 0:
        next_unpaid = _first_unpaid_installment(schedule, principal_paid, interest_paid)
        if next_unpaid:
            scheduled_interest_due = round(next_unpaid["interest_due"], 2)
            scheduled_principal_due = round(
                min(next_unpaid["principal_due"], outstanding_balance),
                2,
            )
            next_due_date = next_unpaid.get("due_date")
        else:
            next_due_date = None
    else:
        next_unpaid = _first_unpaid_installment(schedule, principal_paid, interest_paid)
        next_due_date = next_unpaid.get("due_date") if next_unpaid else None

    # Penalty accrual on overdue unpaid scheduled installment amounts
    accrued_penalty = 0.0
    remaining_applied_to_schedule = round(applied_to_schedule, 2)

    for item in overdue_items:
        installment_due = round(item["payment"], 2)
        applied_to_this = min(remaining_applied_to_schedule, installment_due)
        remaining_applied_to_schedule = round(remaining_applied_to_schedule - applied_to_this, 2)

        unpaid_for_installment = round(installment_due - applied_to_this, 2)
        if unpaid_for_installment <= 0:
            continue

        days_late = (as_of.date() - item["due_date"].date()).days
        accrued_penalty += compute_penalty(
            amount_due=unpaid_for_installment,
            days_late=days_late,
            daily_rate=penalty_rate_daily,
        )

    penalty_due = round(max(accrued_penalty - penalty_paid, 0.0), 2)

    overdue_unpaid_amount = 0.0
    remaining_applied_for_overdue_check = round(applied_to_schedule, 2)
    for item in overdue_items:
        installment_due = round(item["payment"], 2)
        applied_to_this = min(remaining_applied_for_overdue_check, installment_due)
        remaining_applied_for_overdue_check = round(
            remaining_applied_for_overdue_check - applied_to_this, 2
        )
        overdue_unpaid_amount += round(installment_due - applied_to_this, 2)

    overdue_unpaid_amount = round(max(overdue_unpaid_amount, 0.0), 2)

    return {
        "outstanding_balance": outstanding_balance,
        "interest_due": round(max(scheduled_interest_due, 0.0), 2),
        "principal_due": round(max(min(scheduled_principal_due, outstanding_balance), 0.0), 2),
        "penalty_due": penalty_due,
        "due_installments": len(due_items),
        "overdue_installments": len(overdue_items),
        "next_due_date": next_due_date,
        "overdue_unpaid_amount": overdue_unpaid_amount,
        "principal_paid": principal_paid,
        "interest_paid": interest_paid,
        "penalty_paid": penalty_paid,
    }