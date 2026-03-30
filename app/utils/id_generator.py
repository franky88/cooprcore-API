from pymongo import ReturnDocument

from . import utcnow


def _year() -> int:
    return utcnow().year


def _next_sequence(db, counter_key: str) -> int:
    """
    Atomically increments and returns the next sequence number for a key.

    Example counter docs:
    { "_id": "member_id:2026", "seq": 42 }
    { "_id": "employee_id", "seq": 7 }
    { "_id": "transaction_id:20260325", "seq": 105 }
    """
    doc = db.counters.find_one_and_update(
        {"_id": counter_key},
        {
            "$inc": {"seq": 1},
            "$setOnInsert": {
                "created_at": utcnow(),
            },
            "$set": {
                "updated_at": utcnow(),
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(doc["seq"])


def generate_employee_id(db) -> str:
    seq = _next_sequence(db, "employee_id")
    return f"EMP-{str(seq).zfill(4)}"


def generate_member_id(db) -> str:
    year = _year()
    seq = _next_sequence(db, f"member_id:{year}")
    return f"M-{year}-{str(seq).zfill(4)}"


def generate_loan_id(db) -> str:
    year = _year()
    seq = _next_sequence(db, f"loan_id:{year}")
    return f"LN-{year}-{str(seq).zfill(4)}"


def generate_account_id(db) -> str:
    year = _year()
    seq = _next_sequence(db, f"account_id:{year}")
    return f"SA-{year}-{str(seq).zfill(4)}"


def generate_share_id(db) -> str:
    year = _year()
    seq = _next_sequence(db, f"share_id:{year}")
    return f"SH-{year}-{str(seq).zfill(4)}"


def generate_transaction_id(db) -> str:
    stamp = utcnow().strftime("%Y%m%d")
    seq = _next_sequence(db, f"transaction_id:{stamp}")
    return f"TXN-{stamp}-{str(seq).zfill(5)}"


def generate_payment_id(db) -> str:
    year = _year()
    seq = _next_sequence(db, f"payment_id:{year}")
    return f"PMT-{year}-{str(seq).zfill(4)}"


def generate_share_payment_id(db) -> str:
    year = _year()
    seq = _next_sequence(db, f"share_payment_id:{year}")
    return f"SPY-{year}-{str(seq).zfill(4)}"


def generate_dividend_id(db, fiscal_year: int) -> str:
    seq = _next_sequence(db, f"dividend_id:{fiscal_year}")
    return f"DIV-{fiscal_year}-{str(seq).zfill(4)}"

def generate_loan_application_id(db) -> str:
    year = _year()
    seq = _next_sequence(db, f"loan_application_id:{year}")
    return f"LA-{year}-{str(seq).zfill(4)}"