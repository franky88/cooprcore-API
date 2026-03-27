from datetime import datetime
from bson import ObjectId
from ..extensions import mongo


class MemberPortalService:
    @property
    def db(self):
        return mongo.db

    def get_member_user_by_user_id(self, user_id: str):
        try:
            obj_id = ObjectId(user_id)
        except Exception:
            return None

        return self.db.users.find_one(
            {"_id": obj_id, "role": "member", "is_active": True},
            {"password_hash": 0},
        )

    def _get_member_id_by_user_id(self, user_id: str):
        user = self.get_member_user_by_user_id(user_id)
        if not user:
            return None
        return user.get("member_id")

    def get_member_profile_by_user_id(self, user_id: str):
        member_id = self._get_member_id_by_user_id(user_id)
        if not member_id:
            return None

        member = self.db.members.find_one({"member_id": member_id})
        if not member:
            return None

        return self._serialize_doc(member)

    def get_dashboard_summary(self, user_id: str):
        member_id = self._get_member_id_by_user_id(user_id)
        if not member_id:
            return None

        member = self.db.members.find_one({"member_id": member_id})
        if not member:
            return None

        loans = list(
            self.db.loans.find(
                {"member_id": member_id},
                {
                    "_id": 1,
                    "loan_id": 1,
                    "loan_type": 1,
                    "principal": 1,
                    "outstanding_balance": 1,
                    "monthly_amortization": 1,
                    "status": 1,
                    "date_applied": 1,
                    "maturity_date": 1,
                },
            ).sort("date_applied", -1)
        )

        savings = list(
            self.db.savings_accounts.find(
                {"member_id": member_id},
                {
                    "_id": 1,
                    "account_id": 1,
                    "product_type": 1,
                    "status": 1,
                    "current_balance": 1,
                    "date_opened": 1,
                },
            ).sort("date_opened", -1)
        )

        shares = self.db.share_capital.find_one(
            {"member_id": member_id},
            {
                "_id": 1,
                "share_id": 1,
                "subscribed_shares": 1,
                "paid_shares": 1,
                "share_par_value": 1,
                "subscribed_amount": 1,
                "paid_amount": 1,
                "outstanding_amount": 1,
                "percentage_paid": 1,
                "last_payment_date": 1,
            },
        )

        total_savings_balance = sum(float(item.get("current_balance", 0) or 0) for item in savings)
        active_loans = [
            item for item in loans
            if item.get("status") in {"Pending", "Approved", "Released", "Current", "Past Due"}
        ]
        total_loan_balance = sum(float(item.get("outstanding_balance", 0) or 0) for item in active_loans)

        return {
            "member": self._serialize_doc(member),
            "stats": {
                "total_savings_balance": round(total_savings_balance, 2),
                "active_loans_count": len(active_loans),
                "total_loan_balance": round(total_loan_balance, 2),
                "share_paid_amount": round(float((shares or {}).get("paid_amount", 0) or 0), 2),
            },
            "loans": [self._serialize_doc(item) for item in loans],
            "savings": [self._serialize_doc(item) for item in savings],
            "shares": self._serialize_doc(shares) if shares else None,
        }

    def get_member_loans(self, user_id: str):
        member_id = self._get_member_id_by_user_id(user_id)
        if not member_id:
            return None

        loans = list(
            self.db.loans.find(
                {"member_id": member_id},
                {
                    "_id": 1,
                    "loan_id": 1,
                    "loan_type": 1,
                    "principal": 1,
                    "outstanding_balance": 1,
                    "monthly_amortization": 1,
                    "status": 1,
                    "date_applied": 1,
                    "date_released": 1,
                    "maturity_date": 1,
                    "term_months": 1,
                    "interest_rate": 1,
                },
            ).sort("date_applied", -1)
        )

        return {"data": [self._serialize_doc(item) for item in loans]}

    def get_member_savings(self, user_id: str):
        member_id = self._get_member_id_by_user_id(user_id)
        if not member_id:
            return None

        savings = list(
            self.db.savings_accounts.find(
                {"member_id": member_id},
                {
                    "_id": 1,
                    "account_id": 1,
                    "product_type": 1,
                    "status": 1,
                    "current_balance": 1,
                    "date_opened": 1,
                },
            ).sort("date_opened", -1)
        )

        return {"data": [self._serialize_doc(item) for item in savings]}

    def get_member_shares(self, user_id: str):
        member_id = self._get_member_id_by_user_id(user_id)
        if not member_id:
            return None

        shares = self.db.share_capital.find_one(
            {"member_id": member_id},
            {
                "_id": 1,
                "share_id": 1,
                "subscribed_shares": 1,
                "paid_shares": 1,
                "share_par_value": 1,
                "subscribed_amount": 1,
                "paid_amount": 1,
                "outstanding_amount": 1,
                "percentage_paid": 1,
                "last_payment_date": 1,
            },
        )

        return {"data": self._serialize_doc(shares) if shares else None}

    def _serialize_doc(self, doc):
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