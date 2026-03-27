# backend/app/utils/pagination.py
import math


def paginate(cursor, page: int, per_page: int) -> dict:
    """
    Takes a PyMongo cursor (already filtered, sorted),
    applies skip/limit, and returns the standard pagination envelope.
    """
    per_page = min(per_page, 100)  # hard cap
    total = cursor.count()  # NOTE: requires a non-exhausted cursor copy
    data = list(cursor.skip((page - 1) * per_page).limit(per_page))
    return {
        "data": data,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": math.ceil(total / per_page) if total else 0,
        },
    }