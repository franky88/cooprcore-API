from __future__ import annotations

from datetime import datetime
import math
from bson import ObjectId

from ..extensions import mongo
from ..utils.id_generator import generate_loan_id


class LoanApplicationService:
    REVIEWABLE_STATUSES = {"Submitted", "Under Review"}
    APPROVABLE_STATUSES = {"Submitted", "Under Review"}

    @property
    def db(self):
        return mongo.db

    def ensure_indexes(self) -> None:
        self.db.loan_applications.create_index("application_id", unique=True)
        self.db.loan_applications.create_index("member_id")
        self.db.loan_applications.create_index("status")
        self.db.loan_applications.create_index("submitted_at")
        self.db.loan_applications.create_index([("member_id", 1), ("status", 1)])

    def list_applications(
        self,
        page: int = 1,
        per_page: int = 20,
        status: str | None = None,
        search: str | None = None,
    ) -> dict:
        self.ensure_indexes()

        query: dict = {}

        if status:
            query["status"] = status

        if search:
            query["$or"] = [
                {"application_id": {"$regex": search, "$options": "i"}},
                {"member_id": {"$regex": search, "$options": "i"}},
                {"member_name": {"$regex": search, "$options": "i"}},
                {"loan_type": {"$regex": search, "$options": "i"}},
            ]

        total = self.db.loan_applications.count_documents(query)

        applications = list(
            self.db.loan_applications.find(query)
            .sort("submitted_at", -1)
            .skip((page - 1) * per_page)
            .limit(per_page)
        )

        return {
            "data": [self._serialize(doc) for doc in applications],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": math.ceil(total / per_page) if per_page else 1,
            },
        }

    def get_application_by_id(self, application_id: str) -> dict | None:
        application = self.db.loan_applications.find_one({"application_id": application_id})
        return self._serialize(application) if application else None

    def review_application(
        self,
        application_id: str,
        reviewer_user_id: str,
        payload: dict,
    ) -> tuple[dict, int]:
        application = self.db.loan_applications.find_one({"application_id": application_id})
        if not application:
            return {"error": "Loan application not found."}, 404

        if application.get("status") not in self.REVIEWABLE_STATUSES:
            return {"error": "Only submitted or under review applications can be reviewed."}, 400

        reviewer = self._get_staff_user_by_user_id(reviewer_user_id)
        if not reviewer:
            return {"error": "Reviewer account not found."}, 404

        now = datetime.utcnow()

        self.db.loan_applications.update_one(
            {"_id": application["_id"]},
            {
                "$set": {
                    "status": "Under Review",
                    "reviewed_by": reviewer.get("employee_id"),
                    "reviewed_at": now,
                    "review_remarks": payload.get("remarks", ""),
                    "updated_at": now,
                }
            },
        )

        updated = self.db.loan_applications.find_one({"_id": application["_id"]})
        return {"data": self._serialize(updated)}, 200

    def reject_application(
        self,
        application_id: str,
        reviewer_user_id: str,
        payload: dict,
    ) -> tuple[dict, int]:
        application = self.db.loan_applications.find_one({"application_id": application_id})
        if not application:
            return {"error": "Loan application not found."}, 404

        if application.get("status") not in self.APPROVABLE_STATUSES:
            return {"error": "Only submitted or under review applications can be rejected."}, 400

        reviewer = self._get_staff_user_by_user_id(reviewer_user_id)
        if not reviewer:
            return {"error": "Reviewer account not found."}, 404

        now = datetime.utcnow()

        self.db.loan_applications.update_one(
            {"_id": application["_id"]},
            {
                "$set": {
                    "status": "Rejected",
                    "reviewed_by": reviewer.get("employee_id"),
                    "reviewed_at": now,
                    "rejected_reason": payload["rejected_reason"],
                    "review_remarks": payload.get("remarks", ""),
                    "updated_at": now,
                }
            },
        )

        updated = self.db.loan_applications.find_one({"_id": application["_id"]})
        return {"data": self._serialize(updated)}, 200

    def approve_application(
        self,
        application_id: str,
        reviewer_user_id: str,
        payload: dict,
    ) -> tuple[dict, int]:
        application = self.db.loan_applications.find_one({"application_id": application_id})
        if not application:
            return {"error": "Loan application not found."}, 404

        if application.get("status") not in self.APPROVABLE_STATUSES:
            return {"error": "Only submitted or under review applications can be approved."}, 400

        reviewer = self._get_staff_user_by_user_id(reviewer_user_id)
        if not reviewer:
            return {"error": "Approver account not found."}, 404

        member_id = application["member_id"]
        member = self.db.members.find_one(
            {"member_id": member_id},
            {
                "_id": 1,
                "member_id": 1,
                "status": 1,
                "first_name": 1,
                "middle_name": 1,
                "last_name": 1,
            },
        )
        if not member:
            return {"error": "Member record not found."}, 404

        if member.get("status") != "Active":
            return {"error": "Only active members can have loan applications approved."}, 400

        active_loans_count = self.db.loans.count_documents(
            {
                "member_id": member_id,
                "status": {"$in": ["Pending", "Approved", "Released", "Current", "Past Due"]},
            }
        )
        if active_loans_count >= 2:
            return {"error": "Member already has the maximum of 2 active loans."}, 400

        principal = float(application["principal"])
        if principal > 30000 and not application.get("co_makers"):
            return {"error": "Co-maker is required for loan amounts above ₱30,000."}, 400

        now = datetime.utcnow()
        loan_id = generate_loan_id(self.db)

        maturity_date = None
        date_approved = now

        loan_doc = {
            "loan_id": loan_id,
            "member_id": application["member_id"],
            "member_name": application["member_name"],
            "loan_type": application["loan_type"],
            "principal": application["principal"],
            "interest_rate": application["interest_rate"],
            "term_months": application["term_months"],
            "monthly_amortization": application["monthly_amortization"],
            "total_payable": application["total_payable"],
            "total_interest": application["total_interest"],
            "outstanding_balance": application["total_payable"],
            "total_paid": 0.0,
            "payments_made": 0,
            "status": "Approved",
            "purpose": application["purpose"],
            "date_applied": application.get("submitted_at", now),
            "date_approved": date_approved,
            "date_released": None,
            "maturity_date": maturity_date,
            "approved_by": reviewer.get("employee_id"),
            "approved_at": now,
            "rejected_reason": None,
            "co_makers": application.get("co_makers", []),
            "collateral": None,
            "application_id": application["application_id"],
            "created_at": now,
            "updated_at": now,
        }

        self.db.loans.insert_one(loan_doc)

        self.db.loan_applications.update_one(
            {"_id": application["_id"]},
            {
                "$set": {
                    "status": "Approved",
                    "reviewed_by": reviewer.get("employee_id"),
                    "reviewed_at": now,
                    "approved_by": reviewer.get("employee_id"),
                    "approved_at": now,
                    "review_remarks": payload.get("remarks", ""),
                    "converted_loan_id": loan_id,
                    "updated_at": now,
                }
            },
        )

        updated_application = self.db.loan_applications.find_one({"_id": application["_id"]})

        return {
            "data": {
                "application": self._serialize(updated_application),
                "loan": self._serialize(loan_doc),
            }
        }, 200

    def _get_staff_user_by_user_id(self, user_id: str):
        try:
            obj_id = ObjectId(user_id)
        except Exception:
            return None

        return self.db.users.find_one(
            {
                "_id": obj_id,
                "role": {"$in": ["super_admin", "branch_manager", "loan_officer"]},
                "is_active": True,
            },
            {"password_hash": 0},
        )

    def _serialize(self, doc: dict | None) -> dict | None:
        if not doc:
            return None

        serialized = {}
        for key, value in doc.items():
            if key == "_id":
                serialized["id"] = str(value)
            elif isinstance(value, datetime):
                serialized[key] = value.isoformat()
            else:
                serialized[key] = value
        return serialized