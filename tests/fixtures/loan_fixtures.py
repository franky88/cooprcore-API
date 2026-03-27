# backend/tests/fixtures/loan_fixtures.py


def valid_loan_payload(member_id: str, overrides: dict | None = None) -> dict:
    base = {
        "member_id": member_id,
        "loan_type": "Multi-Purpose",
        "principal": 20000,
        "term_months": 12,
        "purpose": "Home improvement and furniture purchase",
        "co_makers": [],
        "collateral": None,
    }
    if overrides:
        base.update(overrides)
    return base


def payment_payload(overrides: dict | None = None) -> dict:
    base = {
        "amount_paid": 1843.21,
        "payment_method": "Cash",
        "or_number": "OR-TEST-00001",
        "remarks": "Monthly payment",
    }
    if overrides:
        base.update(overrides)
    return base