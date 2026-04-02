from __future__ import annotations

from datetime import datetime
from bson import ObjectId

from ..extensions import mongo
from ..utils.id_generator import generate_loan_application_id
from ..utils.loan_calculator import compute_amortization, LOAN_TYPE_CONFIG


class MemberLoanApplicationService:
    @property
    def db(self):
        return mongo.db

    def ensure_indexes(self) -> None:
        self.db.loan_applications.create_index("application_id", unique=True)
        self.db.loan_applications.create_index("member_id")
        self.db.loan_applications.create_index("status")
        self.db.loan_applications.create_index("submitted_at")
        self.db.loan_applications.create_index([("member_id", 1), ("status", 1)])

    def submit_application(self, user_id: str, payload: dict) -> tuple[dict, int]:
        self.ensure_indexes()

        member_user = self._get_member_user_by_user_id(user_id)
        if not member_user:
            return {"error": "Member account not found."}, 404

        member_id = member_user.get("member_id")
        if not member_id:
            return {"error": "Member account is not linked to a member record."}, 400

        member = self.db.members.find_one(
            {"member_id": member_id},
            {
                "_id": 1,
                "member_id": 1,
                "first_name": 1,
                "last_name": 1,
                "middle_name": 1,
                "status": 1,
                "email": 1,
                "phone": 1,
                "monthly_income": 1,
                "date_admitted": 1,
            },
        )
        if not member:
            return {"error": "Member record not found."}, 404

        if member.get("status") != "Active":
            return {"error": "Only active members can apply for loans."}, 400

        active_loans_count = self.db.loans.count_documents(
            {
                "member_id": member_id,
                "status": {"$in": ["Pending", "Approved", "Released", "Current", "Past Due"]},
            }
        )
        if active_loans_count >= 2:
            return {"error": "Member already has the maximum of 2 active loans."}, 400

        principal = float(payload["principal"])
        loan_type = payload["loan_type"]
        term_months = int(payload["term_months"])
        co_makers = payload.get("co_makers", [])

        co_maker_error = self._validate_co_makers(member_id=member_id, co_makers=co_makers)
        if co_maker_error:
            return {"error": co_maker_error}, 400

        config = LOAN_TYPE_CONFIG.get(loan_type, {})
        interest_rate = float(config.get("annual_interest_rate", config.get("interest_rate", 0)) or 0)

        amortization = compute_amortization(
            principal=principal,
            annual_rate=interest_rate,
            term_months=term_months,
        )

        application_id = generate_loan_application_id(self.db)
        now = datetime.utcnow()
        member_name = self._build_member_name(member)

        application_doc = {
            "application_id": application_id,
            "member_id": member_id,
            "member_name": member_name,
            "loan_type": loan_type,
            "principal": principal,
            "interest_rate": interest_rate,
            "term_months": term_months,
            "monthly_amortization": amortization["monthly_amortization"],
            "total_payable": amortization["total_payable"],
            "total_interest": amortization["total_interest"],
            "purpose": payload["purpose"],
            "co_makers": co_makers,
            "remarks": payload.get("remarks", ""),
            "status": "Submitted",
            "submitted_via": "member_portal",
            "submitted_at": now,
            "reviewed_by": None,
            "reviewed_at": None,
            "approved_by": None,
            "approved_at": None,
            "rejected_reason": None,
            "created_at": now,
            "updated_at": now,
        }

        self.db.loan_applications.insert_one(application_doc)

        return {"data": self._serialize(application_doc)}, 201

    def get_member_applications(self, user_id: str) -> tuple[dict, int]:
        member_user = self._get_member_user_by_user_id(user_id)
        if not member_user or not member_user.get("member_id"):
            return {"error": "Member account not found."}, 404

        member_id = member_user["member_id"]

        applications = list(
            self.db.loan_applications.find(
                {"member_id": member_id},
                {
                    "_id": 1,
                    "application_id": 1,
                    "member_id": 1,
                    "member_name": 1,
                    "loan_type": 1,
                    "principal": 1,
                    "interest_rate": 1,
                    "term_months": 1,
                    "monthly_amortization": 1,
                    "total_payable": 1,
                    "total_interest": 1,
                    "purpose": 1,
                    "co_makers": 1,
                    "remarks": 1,
                    "status": 1,
                    "submitted_via": 1,
                    "submitted_at": 1,
                    "reviewed_by": 1,
                    "reviewed_at": 1,
                    "approved_by": 1,
                    "approved_at": 1,
                    "rejected_reason": 1,
                    "created_at": 1,
                    "updated_at": 1,
                },
            ).sort("submitted_at", -1)
        )

        return {"data": [self._serialize(doc) for doc in applications]}, 200

    def get_member_application_by_id(self, user_id: str, application_id: str) -> tuple[dict, int]:
        member_user = self._get_member_user_by_user_id(user_id)
        if not member_user or not member_user.get("member_id"):
            return {"error": "Member account not found."}, 404

        member_id = member_user["member_id"]

        application = self.db.loan_applications.find_one(
            {"application_id": application_id, "member_id": member_id}
        )
        if not application:
            return {"error": "Loan application not found."}, 404

        return {"data": self._serialize(application)}, 200

    def _get_member_user_by_user_id(self, user_id: str):
        try:
            obj_id = ObjectId(user_id)
        except Exception:
            return None

        return self.db.users.find_one(
            {"_id": obj_id, "role": "member", "is_active": True},
            {"password_hash": 0},
        )

    def _validate_co_makers(self, member_id: str, co_makers: list[dict]) -> str | None:
        seen = set()

        for co_maker in co_makers:
            co_maker_member_id = co_maker.get("member_id", "").strip()

            if not co_maker_member_id:
                return "Invalid co-maker member ID."

            if co_maker_member_id == member_id:
                return "Member cannot assign themselves as co-maker."

            if co_maker_member_id in seen:
                return "Duplicate co-maker is not allowed."
            seen.add(co_maker_member_id)

            member = self.db.members.find_one(
                {"member_id": co_maker_member_id},
                {"member_id": 1, "status": 1, "first_name": 1, "last_name": 1},
            )
            if not member:
                return f"Co-maker {co_maker_member_id} not found."

            if member.get("status") != "Active":
                return f"Co-maker {co_maker_member_id} must be an active member."

        return None

    def _build_member_name(self, member: dict) -> str:
        parts = [
            member.get("first_name", ""),
            member.get("middle_name", ""),
            member.get("last_name", ""),
        ]
        return " ".join(part.strip() for part in parts if part and part.strip())

    def _serialize(self, doc: dict) -> dict:
        serialized = {}
        for key, value in doc.items():
            if key == "_id":
                serialized["id"] = str(value)
            elif isinstance(value, datetime):
                serialized[key] = value.isoformat()
            else:
                serialized[key] = value
        return serialized