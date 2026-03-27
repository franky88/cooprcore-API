# backend/app/utils/settings_reader.py

from ..extensions import mongo

_FALLBACK_LOAN_RATES = {
    "Multi-Purpose": {"annual_rate": 12.0, "max_term_months": 36},
    "Emergency":     {"annual_rate": 10.0, "max_term_months": 12},
    "Business":      {"annual_rate": 14.0, "max_term_months": 48},
    "Salary":        {"annual_rate":  8.0, "max_term_months":  6},
    "Housing":       {"annual_rate": 10.0, "max_term_months": 60},
    "Educational":   {"annual_rate":  8.0, "max_term_months": 24},
}

def get_loan_type_config() -> dict:
    """
    Returns loan type config keyed by loan type name.
    Reads from settings collection first, falls back to hardcoded defaults.
    Shape: { "Multi-Purpose": {"annual_rate": 12.0, "max_term_months": 36}, ... }
    """
    try:
        settings = mongo.db.settings.find_one({"key": "global"}) or {}
        loan_rates = settings.get("loan_rates") or {}

        if not loan_rates:
            return _FALLBACK_LOAN_RATES

        # Merge with fallbacks for any missing types
        config = {}
        for loan_type, fallback in _FALLBACK_LOAN_RATES.items():
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
        # If DB is unavailable, fall back to hardcoded defaults
        return _FALLBACK_LOAN_RATES


def get_setting(key: str, default=None):
    """Read a single setting value from the settings collection."""
    try:
        settings = mongo.db.settings.find_one({"key": "global"}) or {}
        return settings.get(key, default)
    except Exception:
        return default