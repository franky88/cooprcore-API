# backend/tests/fixtures/share_fixtures.py


def subscribe_payload(additional_shares: int = 50, overrides: dict | None = None) -> dict:
    base = {
        "additional_shares": additional_shares,
        "remarks": "Initial subscription",
    }
    if overrides:
        base.update(overrides)
    return base


def payment_payload(amount: float = 1000.0, overrides: dict | None = None) -> dict:
    base = {
        "amount_paid": amount,
        "or_number": "OR-SH-00001",
        "remarks": "Share capital payment",
    }
    if overrides:
        base.update(overrides)
    return base


def dividend_payload(rate: float = 10.0, year: int = 2099, overrides: dict | None = None) -> dict:
    """Uses year 2099 by default so dividend tests don't collide with each other."""
    base = {
        "dividend_rate": rate,
        "fiscal_year": year,
        "remarks": f"Annual dividend at {rate}% for FY {year}",
    }
    if overrides:
        base.update(overrides)
    return base