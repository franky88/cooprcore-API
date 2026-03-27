# backend/app/utils/__init__.py
from datetime import datetime, timezone


def utcnow() -> datetime:
    """
    Returns the current UTC time as a timezone-NAIVE datetime.
    Use this everywhere instead of datetime.utcnow() (deprecated in 3.12).
    PyMongo stores and compares naive datetimes as UTC, so we keep them naive
    for consistency across the entire codebase.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)