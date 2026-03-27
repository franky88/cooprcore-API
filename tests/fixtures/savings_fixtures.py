# backend/tests/fixtures/savings_fixtures.py


def open_account_payload(member_id: str, overrides: dict | None = None) -> dict:
    base = {
        "member_id": member_id,
        "product_type": "Regular Savings",
        "initial_deposit": 500.0,
        "passbook_number": "PB-TEST-001",
    }
    if overrides:
        base.update(overrides)
    return base


def deposit_payload(overrides: dict | None = None) -> dict:
    base = {
        "transaction_type": "Deposit",
        "amount": 1000.0,
        "payment_method": "Cash",
        "or_number": "OR-DEP-00001",
        "remarks": "Test deposit",
    }
    if overrides:
        base.update(overrides)
    return base


def withdrawal_payload(overrides: dict | None = None) -> dict:
    base = {
        "transaction_type": "Withdrawal",
        "amount": 200.0,
        "payment_method": "Cash",
        "or_number": "OR-WD-00001",
        "remarks": "Test withdrawal",
    }
    if overrides:
        base.update(overrides)
    return base