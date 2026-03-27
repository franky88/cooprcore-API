# backend/app/utils/validators.py
import re


def validate_login(data: dict | None) -> dict:
    errors: dict[str, list[str]] = {}
    if not data:
        return {"body": ["Request body is required"]}

    if not data.get("email"):
        errors["email"] = ["Email is required"]
    elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", data["email"]):
        errors["email"] = ["Invalid email format"]

    if not data.get("password"):
        errors["password"] = ["Password is required"]

    return errors


def validate_password_strength(password: str) -> list[str]:
    """Returns a list of violation messages; empty list = valid."""
    errors = []
    if len(password) < 8:
        errors.append("Password must be at least 8 characters")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        errors.append("Password must contain at least one lowercase letter")
    if not re.search(r"\d", password):
        errors.append("Password must contain at least one number")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        errors.append("Password must contain at least one special character")
    return errors