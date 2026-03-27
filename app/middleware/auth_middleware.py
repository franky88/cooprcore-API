# backend/app/middleware/auth_middleware.py
from functools import wraps
from flask import jsonify
from flask_jwt_extended import get_jwt


def roles_required(*roles: str):
    """
    Decorator that restricts a route to users whose JWT claim 'role'
    matches one of the provided roles.

    Must be applied AFTER @jwt_required().

    Usage:
        @members_bp.post("/")
        @jwt_required()
        @roles_required("super_admin", "branch_manager")
        def create_member(): ...
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            claims = get_jwt()
            if claims.get("role") not in roles:
                return jsonify({"error": "Insufficient permissions"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator