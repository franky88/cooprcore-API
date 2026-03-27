# backend/app/services/user_service.py
import math
from datetime import datetime
from bson import ObjectId
from bson.errors import InvalidId
import bcrypt

from ..extensions import mongo
from ..utils.id_generator import generate_employee_id
from ..schemas.user_schema import (
    CreateUserSchema,
    UpdateUserSchema,
    ChangePasswordSchema,
    UserResponseSchema,
)
from ..middleware.audit_middleware import log_audit
from ..utils import utcnow

create_schema = CreateUserSchema()
update_schema = UpdateUserSchema()
change_pw_schema = ChangePasswordSchema()
response_schema = UserResponseSchema()


class UserService:

    @property
    def db(self):
        return mongo.db

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _serialize(self, doc: dict | None) -> dict | None:
        if doc is None:
            return None
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        doc.pop("password_hash", None)
        return doc

    def _get_by_object_id(self, oid: str) -> dict | None:
        try:
            return self.db.users.find_one(
                {"_id": ObjectId(oid)},
                {"password_hash": 0},
            )
        except (InvalidId, Exception):
            return None

    def _hash_password(self, plain: str) -> bytes:
        return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12))

    # ------------------------------------------------------------------ #
    # Read
    # ------------------------------------------------------------------ #

    def get_users(
        self,
        page: int = 1,
        per_page: int = 20,
        role: str | None = None,
        is_active: bool | None = None,
        search: str | None = None,
    ) -> dict:
        per_page = min(per_page, 100)
        query: dict = {}

        if role:
            query["role"] = role
        if is_active is not None:
            query["is_active"] = is_active
        if search:
            query["$or"] = [
                {"full_name": {"$regex": search, "$options": "i"}},
                {"email": {"$regex": search, "$options": "i"}},
                {"employee_id": {"$regex": search, "$options": "i"}},
            ]

        total = self.db.users.count_documents(query)
        users = list(
            self.db.users.find(query, {"password_hash": 0})
            .sort("full_name", 1)
            .skip((page - 1) * per_page)
            .limit(per_page)
        )

        return {
            "data": [self._serialize(u) for u in users],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": math.ceil(total / per_page) if total else 0,
            },
        }

    def get_by_id(self, user_id: str) -> dict | None:
        user = self._get_by_object_id(user_id)
        return self._serialize(user)

    def get_by_email(self, email: str) -> dict | None:
        """Returns the full document INCLUDING password_hash (for auth only)."""
        return self.db.users.find_one({"email": email.lower().strip()})

    # ------------------------------------------------------------------ #
    # Create
    # ------------------------------------------------------------------ #

    def create_user(self, data: dict, created_by: str = "system") -> dict:
        errors = create_schema.validate(data)
        if errors:
            return {"error": errors}

        email = data["email"].lower().strip()

        if self.db.users.find_one({"email": email}):
            return {"error": {"email": ["Email is already registered"]}}

        employee_id = generate_employee_id(self.db)
        now = utcnow()

        user_doc = {
            "employee_id": employee_id,
            "full_name": data["full_name"].strip(),
            "email": email,
            "password_hash": self._hash_password(data["password"]),
            "role": data["role"],
            "branch": data.get("branch", "Main Branch"),
            "is_active": True,
            "created_at": now,
            "updated_at": now,
            "last_login": None,
        }

        result = self.db.users.insert_one(user_doc)
        new_id = str(result.inserted_id)

        log_audit(
            action="CREATE_USER",
            resource="users",
            resource_id=employee_id,
            details={"role": data["role"], "email": email},
        )

        return self.get_by_id(new_id)

    # ------------------------------------------------------------------ #
    # Update
    # ------------------------------------------------------------------ #

    def update_user(self, user_id: str, data: dict, updated_by: str = "system") -> dict:
        errors = update_schema.validate(data)
        if errors:
            return {"error": errors}

        user = self._get_by_object_id(user_id)
        if not user:
            return {"error": "User not found"}

        allowed_fields = {"full_name", "role", "branch", "is_active"}
        updates = {k: v for k, v in data.items() if k in allowed_fields}

        if not updates:
            return {"error": "No valid fields provided for update"}

        updates["updated_at"] = utcnow()

        self.db.users.update_one({"_id": ObjectId(user_id)}, {"$set": updates})

        log_audit(
            action="UPDATE_USER",
            resource="users",
            resource_id=user["employee_id"],
            details={"changes": list(updates.keys())},
        )

        return self.get_by_id(user_id)

    # ------------------------------------------------------------------ #
    # Password management
    # ------------------------------------------------------------------ #

    def change_password(self, user_id: str, data: dict) -> dict:
        errors = change_pw_schema.validate(data)
        if errors:
            return {"error": errors}

        # Need the full document to verify current password
        try:
            user_doc = self.db.users.find_one({"_id": ObjectId(user_id)})
        except (InvalidId, Exception):
            return {"error": "User not found"}

        if not user_doc:
            return {"error": "User not found"}

        if not bcrypt.checkpw(
            data["current_password"].encode(), user_doc["password_hash"]
        ):
            return {"error": {"current_password": ["Current password is incorrect"]}}

        new_hash = self._hash_password(data["new_password"])
        self.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"password_hash": new_hash, "updated_at": utcnow()}},
        )

        log_audit(
            action="CHANGE_PASSWORD",
            resource="users",
            resource_id=user_doc["employee_id"],
        )

        return {"message": "Password updated successfully"}

    def admin_reset_password(self, user_id: str, new_password: str) -> dict:
        """super_admin only — resets without requiring current password."""
        from ..utils.validators import validate_password_strength
        pw_errors = validate_password_strength(new_password)
        if pw_errors:
            return {"error": {"new_password": pw_errors}}

        try:
            user_doc = self.db.users.find_one(
                {"_id": ObjectId(user_id)}, {"employee_id": 1}
            )
        except (InvalidId, Exception):
            return {"error": "User not found"}

        if not user_doc:
            return {"error": "User not found"}

        new_hash = self._hash_password(new_password)
        self.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"password_hash": new_hash, "updated_at": utcnow()}},
        )

        log_audit(
            action="ADMIN_RESET_PASSWORD",
            resource="users",
            resource_id=user_doc["employee_id"],
        )

        return {"message": "Password reset successfully"}

    # ------------------------------------------------------------------ #
    # Record last login (called by auth service)
    # ------------------------------------------------------------------ #

    def record_login(self, user_id_str: str) -> None:
        try:
            self.db.users.update_one(
                {"_id": ObjectId(user_id_str)},
                {"$set": {"last_login": utcnow()}},
            )
        except Exception:
            pass