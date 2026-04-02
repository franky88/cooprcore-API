from __future__ import annotations

from datetime import datetime, timedelta
from random import randint
import hashlib

from pymongo import ReturnDocument
import bcrypt

from ..extensions import mongo
from ..utils.email_sender import send_email
from ..utils import utcnow


class MemberAuthService:
    OTP_EXPIRY_MINUTES = 10
    OTP_MAX_ATTEMPTS = 5

    @property
    def db(self):
        return mongo.db

    def ensure_indexes(self) -> None:
        self.db.users.create_index("email", unique=True)
        self.db.users.create_index("member_id", unique=True, sparse=True)
        self.db.members.create_index("member_id", unique=True)
        self.db.member_activation_otps.create_index("member_id")
        self.db.member_activation_otps.create_index("email")
        self.db.member_activation_otps.create_index("expires_at", expireAfterSeconds=0)

    def start_activation(self, payload: dict) -> dict:
        self.ensure_indexes()

        member_id = payload["member_id"].strip()
        email = payload["email"].strip().lower()
        date_of_birth = payload["date_of_birth"]

        member = self.db.members.find_one(
            {"member_id": member_id},
            {
                "_id": 1,
                "member_id": 1,
                "first_name": 1,
                "last_name": 1,
                "email": 1,
                "date_of_birth": 1,
                "status": 1,
            },
        )

        if not member:
            return {"error": "Member record not found."}

        stored_email = (member.get("email") or "").strip().lower()
        if stored_email != email:
            return {"error": "Email does not match our member records."}

        if member.get("status") != "Active":
            return {"error": "Only active members can activate portal access."}

        stored_dob = member.get("date_of_birth")
        if not self._dates_match(stored_dob, date_of_birth):
            return {"error": "Date of birth does not match our member records."}

        existing_user = self.db.users.find_one(
            {"member_id": member_id, "role": "member"},
            {"_id": 1},
        )
        if existing_user:
            return {"error": "Portal account already activated for this member."}

        otp = f"{randint(0, 999999):06d}"
        otp_hash = self._hash_otp(otp)
        now = utcnow()
        expires_at = now + timedelta(minutes=self.OTP_EXPIRY_MINUTES)

        self.db.member_activation_otps.find_one_and_update(
            {"member_id": member_id},
            {
                "$set": {
                    "member_id": member_id,
                    "email": email,
                    "otp_hash": otp_hash,
                    "attempts": 0,
                    "expires_at": expires_at,
                    "created_at": now,
                    "verified": False,
                }
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

        try:
            send_email(
                to_email=email,
                subject="Your CoopCore Portal Activation Code",
                body=(
                    f"Hello {member.get('first_name', 'Member')},\n\n"
                    f"Your CoopCore portal activation code is: {otp}\n\n"
                    f"This code expires in {self.OTP_EXPIRY_MINUTES} minutes.\n"
                    f"If you did not request this, please ignore this email."
                ),
            )
        except Exception as e:
            print("EMAIL ERROR:", str(e))
            return {"error": "Failed to send activation email."}

        return {
            "data": {
                "message": "Activation code sent successfully.",
                "member_id": member_id,
                "email": email,
                "expires_in_minutes": self.OTP_EXPIRY_MINUTES,
            }
        }

    def complete_activation(self, payload: dict) -> dict:
        self.ensure_indexes()

        member_id = payload["member_id"].strip()
        otp = payload["otp"].strip()
        password = payload["password"]

        otp_doc = self.db.member_activation_otps.find_one({"member_id": member_id})
        if not otp_doc:
            return {"error": "No activation request found for this member."}

        now = utcnow()
        expires_at = otp_doc.get("expires_at")
        if not expires_at or expires_at < now:
            return {"error": "Activation code has expired. Please request a new one."}

        if int(otp_doc.get("attempts", 0)) >= self.OTP_MAX_ATTEMPTS:
            return {"error": "Too many invalid attempts. Please request a new code."}

        if otp_doc.get("otp_hash") != self._hash_otp(otp):
            self.db.member_activation_otps.update_one(
                {"_id": otp_doc["_id"]},
                {"$inc": {"attempts": 1}},
            )
            return {"error": "Invalid activation code."}

        member = self.db.members.find_one(
            {"member_id": member_id, "status": "Active"},
            {
                "_id": 1,
                "member_id": 1,
                "email": 1,
                "first_name": 1,
                "last_name": 1,
                "status": 1,
            },
        )
        if not member:
            return {"error": "Active member record not found."}

        existing_user = self.db.users.find_one(
            {"member_id": member_id, "role": "member"},
            {"_id": 1},
        )
        if existing_user:
            return {"error": "Portal account already activated for this member."}

        full_name = f"{member.get('first_name', '')} {member.get('last_name', '')}".strip()

        self.db.users.insert_one(
            {
                "name": full_name,
                "email": member["email"].lower().strip(),
                "password_hash": bcrypt.hashpw(
                    password.encode("utf-8"),
                    bcrypt.gensalt(),
                ).decode("utf-8"),
                "role": "member",
                "member_id": member_id,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
                "last_login_at": None,
            }
        )

        self.db.members.update_one(
            {"_id": member["_id"]},
            {
                "$set": {
                    "portal_enabled": True,
                    "portal_activated_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                }
            },
        )

        self.db.member_activation_otps.delete_one({"_id": otp_doc["_id"]})

        return {
            "data": {
                "message": "Portal account activated successfully."
            }
        }

    @staticmethod
    def _hash_otp(otp: str) -> str:
        return hashlib.sha256(otp.encode("utf-8")).hexdigest()

    def _dates_match(self, stored_value, input_date) -> bool:
        if not stored_value:
            return False

        if isinstance(stored_value, datetime):
            return stored_value.date() == input_date

        if isinstance(stored_value, str):
            try:
                return datetime.fromisoformat(stored_value).date() == input_date
            except ValueError:
                return stored_value == input_date.isoformat()

        return False