import bcrypt
from flask_jwt_extended import create_access_token, create_refresh_token

from ..extensions import mongo
from ..utils.validators import validate_login
from ..middleware.audit_middleware import log_audit
from .user_service import UserService

user_service = UserService()


class AuthService:
    def login(self, data: dict) -> dict:
        errors = validate_login(data)
        if errors:
            return {"error": errors}, 400

        email = data["email"].strip().lower()
        password = data["password"]

        user_doc = user_service.get_by_email(email)

        # Constant-time check fallback
        dummy_hash = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt())
        stored_hash = user_doc["password_hash"] if user_doc else dummy_hash

        if isinstance(stored_hash, str):
            stored_hash = stored_hash.encode("utf-8")

        password_ok = bcrypt.checkpw(password.encode("utf-8"), stored_hash)

        if not user_doc or not password_ok:
            return {"error": "Invalid email or password"}, 401

        if not user_doc.get("is_active"):
            return {"error": "Account is deactivated. Contact your administrator."}, 403

        user_id = str(user_doc["_id"])
        role = user_doc["role"]

        is_member = role == "member"

        display_name = (
            user_doc.get("name")
            or user_doc.get("full_name")
            or f"{user_doc.get('first_name', '')} {user_doc.get('last_name', '')}".strip()
            or user_doc.get("email")
        )

        additional_claims = {
            "role": role,
            "name": display_name,
        }

        if is_member:
            additional_claims["member_id"] = user_doc.get("member_id")
        else:
            additional_claims["employee_id"] = user_doc.get("employee_id")

        access_token = create_access_token(
            identity=user_id,
            additional_claims=additional_claims,
        )
        refresh_token = create_refresh_token(identity=user_id)

        user_service.record_login(user_id)

        log_audit(
            action="LOGIN",
            resource="users",
            resource_id=user_doc.get("member_id") if is_member else user_doc.get("employee_id"),
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": {
                "id": user_id,
                "name": display_name,
                "email": user_doc["email"],
                "role": role,
                "member_id": user_doc.get("member_id"),
                "employee_id": user_doc.get("employee_id"),
                "branch": user_doc.get("branch"),
            },
        }, 200