# backend/app/services/admin_service.py
import math
from datetime import datetime, date
from ..extensions import mongo
from ..middleware.audit_middleware import log_audit
from ..schemas.admin_schema import UpdateSettingsSchema, AuditLogFilterSchema
from ..utils import utcnow

settings_schema = UpdateSettingsSchema()
audit_filter_schema = AuditLogFilterSchema()

# ------------------------------------------------------------------ #
# Default cooperative settings stored in the `settings` collection.
# Only one document exists (singleton pattern keyed by "key": "global").
# ------------------------------------------------------------------ #
DEFAULT_SETTINGS = {
    "coop_name": "CoopCore Multi-Purpose Cooperative",
    "address": "",
    "contact_email": "",
    "contact_phone": "",
    "default_loan_rate": 12.0,
    "default_savings_rate": 3.0,
    "share_par_value": 100.0,
    "max_active_loans": 2,
    "comaker_threshold": 30000.0,
    "withholding_tax_rate": 20.0,
    "penalty_rate_monthly": 3.0,
    "dormancy_months": 12,
    "fiscal_year_start_month": 1,   # January
    "loan_rates": {
        "Multi-Purpose": {"rate": 12.0, "max_term": 36},
        "Emergency":     {"rate": 10.0, "max_term": 12},
        "Business":      {"rate": 14.0, "max_term": 48},
        "Salary":        {"rate":  8.0, "max_term":  6},
        "Housing":       {"rate": 10.0, "max_term": 60},
        "Educational":   {"rate":  8.0, "max_term": 24},
    },
}


class AdminService:

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
        doc.pop("_id", None)
        for field in ("created_at", "updated_at"):
            val = doc.get(field)
            if isinstance(val, (datetime, date)):
                doc[field] = val.isoformat()
        return doc

    # ------------------------------------------------------------------ #
    # Settings
    # ------------------------------------------------------------------ #

    def get_settings(self) -> dict:
        doc = self.db.settings.find_one({"key": "global"})
        if not doc:
            # Bootstrap defaults on first call
            now = utcnow()
            self.db.settings.insert_one(
                {"key": "global", **DEFAULT_SETTINGS,
                 "created_at": now, "updated_at": now}
            )
            doc = self.db.settings.find_one({"key": "global"})
        return self._serialize(doc)

    def update_settings(self, data: dict, updated_by: str) -> dict:
        errors = settings_schema.validate(data)
        if errors:
            return {"error": errors}

        cleaned = settings_schema.load(data)
        if not cleaned:
            return {"error": "No valid settings fields provided"}

        cleaned["updated_at"] = utcnow()

        self.db.settings.update_one(
            {"key": "global"},
            {"$set": cleaned},
            upsert=True,
        )

        log_audit(
            action="UPDATE_SETTINGS",
            resource="settings",
            resource_id="global",
            details={"updated_by": updated_by, "fields": list(cleaned.keys())},
        )

        return self.get_settings()

    # ------------------------------------------------------------------ #
    # Audit logs
    # ------------------------------------------------------------------ #

    def get_audit_logs(
        self,
        page: int = 1,
        per_page: int = 50,
        actor_id: str | None = None,
        resource: str | None = None,
        action: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        # Validate and coerce query params through schema
        raw = {
            "page": page, "per_page": per_page,
            "actor_id": actor_id, "resource": resource,
            "action": action, "date_from": date_from, "date_to": date_to,
        }
        errors = audit_filter_schema.validate(raw)
        if errors:
            return {"error": errors}

        cleaned = audit_filter_schema.load(raw)
        per_page = cleaned["per_page"]
        page = cleaned["page"]

        query: dict = {}
        if cleaned.get("actor_id"):
            query["actor_id"] = cleaned["actor_id"]
        if cleaned.get("resource"):
            query["resource"] = cleaned["resource"]
        if cleaned.get("action"):
            query["action"] = {"$regex": cleaned["action"], "$options": "i"}

        date_filter: dict = {}
        if cleaned.get("date_from"):
            try:
                date_filter["$gte"] = datetime.fromisoformat(cleaned["date_from"])
            except ValueError:
                pass
        if cleaned.get("date_to"):
            try:
                date_filter["$lte"] = datetime.fromisoformat(cleaned["date_to"])
            except ValueError:
                pass
        if date_filter:
            query["created_at"] = date_filter

        total = self.db.audit_logs.count_documents(query)
        docs = list(
            self.db.audit_logs.find(query, {"_id": 0})
            .sort("created_at", -1)
            .skip((page - 1) * per_page)
            .limit(per_page)
        )

        for doc in docs:
            val = doc.get("created_at")
            if isinstance(val, datetime):
                doc["created_at"] = val.isoformat()

        return {
            "data": docs,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": math.ceil(total / per_page) if total else 0,
            },
        }

    # ------------------------------------------------------------------ #
    # Reports
    # ------------------------------------------------------------------ #

    def report_members(
        self,
        status: str | None = None,
        membership_type: str | None = None,
    ) -> dict:
        """
        Member listing report with aggregate totals.
        """
        query: dict = {}
        if status:
            query["status"] = status
        if membership_type:
            query["membership_type"] = membership_type

        members = list(
            self.db.members.find(
                query,
                {
                    "member_id": 1, "first_name": 1, "last_name": 1,
                    "membership_type": 1, "status": 1, "phone": 1,
                    "email": 1, "date_admitted": 1, "monthly_income": 1,
                },
            ).sort([("last_name", 1), ("first_name", 1)])
        )

        # Serialize dates
        for m in members:
            m.pop("_id", None)
            val = m.get("date_admitted")
            if isinstance(val, datetime):
                m["date_admitted"] = val.isoformat()

        # Aggregate counts by status
        pipeline = [
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]
        status_counts = {
            r["_id"]: r["count"]
            for r in self.db.members.aggregate(pipeline)
        }

        return {
            "total": len(members),
            "status_counts": status_counts,
            "members": members,
        }

    def report_loans(self, status: str | None = None) -> dict:
        """
        Loan aging and portfolio report.
        Groups loans by status with outstanding balance totals.
        """
        query: dict = {}
        if status:
            query["status"] = status

        loans = list(
            self.db.loans.find(
                query,
                {
                    "loan_id": 1, "member_id": 1, "member_name": 1,
                    "loan_type": 1, "principal": 1, "outstanding_balance": 1,
                    "monthly_amortization": 1, "status": 1,
                    "date_released": 1, "maturity_date": 1,
                    "payments_made": 1, "term_months": 1,
                },
            ).sort("maturity_date", 1)
        )

        for loan in loans:
            loan.pop("_id", None)
            for field in ("date_released", "maturity_date"):
                val = loan.get(field)
                if isinstance(val, datetime):
                    loan[field] = val.isoformat()

            # Compute days overdue for Past Due loans
            if loan.get("status") == "Past Due" and loan.get("maturity_date"):
                try:
                    maturity = datetime.fromisoformat(loan["maturity_date"])
                    loan["days_overdue"] = max((utcnow() - maturity).days, 0)
                except Exception:
                    loan["days_overdue"] = 0
            else:
                loan["days_overdue"] = 0

        # Portfolio summary pipeline
        pipeline = [
            {
                "$group": {
                    "_id": "$status",
                    "count": {"$sum": 1},
                    "total_outstanding": {"$sum": "$outstanding_balance"},
                    "total_principal": {"$sum": "$principal"},
                }
            },
            {"$sort": {"_id": 1}},
        ]
        summary = {
            r["_id"]: {
                "count": r["count"],
                "total_outstanding": round(r["total_outstanding"], 2),
                "total_principal": round(r["total_principal"], 2),
            }
            for r in self.db.loans.aggregate(pipeline)
        }

        total_portfolio = sum(
            v["total_outstanding"] for v in summary.values()
        )

        return {
            "total_loans": len(loans),
            "total_portfolio_outstanding": round(total_portfolio, 2),
            "summary_by_status": summary,
            "loans": loans,
        }

    def report_savings(self, product_type: str | None = None) -> dict:
        """
        Savings portfolio summary report.
        """
        query: dict = {"status": {"$ne": "Closed"}}
        if product_type:
            query["product_type"] = product_type

        accounts = list(
            self.db.savings_accounts.find(
                query,
                {
                    "account_id": 1, "member_id": 1, "member_name": 1,
                    "product_type": 1, "status": 1, "current_balance": 1,
                    "interest_rate": 1, "date_opened": 1,
                    "last_transaction_date": 1,
                },
            ).sort("current_balance", -1)
        )

        for acct in accounts:
            acct.pop("_id", None)
            for field in ("date_opened", "last_transaction_date"):
                val = acct.get(field)
                if isinstance(val, datetime):
                    acct[field] = val.isoformat()

        # Aggregate by product type
        pipeline = [
            {"$match": {"status": {"$ne": "Closed"}}},
            {
                "$group": {
                    "_id": "$product_type",
                    "count": {"$sum": 1},
                    "total_balance": {"$sum": "$current_balance"},
                }
            },
            {"$sort": {"_id": 1}},
        ]
        summary = {
            r["_id"]: {
                "count": r["count"],
                "total_balance": round(r["total_balance"], 2),
            }
            for r in self.db.savings_accounts.aggregate(pipeline)
        }

        total_deposits = sum(v["total_balance"] for v in summary.values())

        return {
            "total_accounts": len(accounts),
            "total_deposits": round(total_deposits, 2),
            "summary_by_product": summary,
            "accounts": accounts,
        }

    def report_shares(self) -> dict:
        """
        Share capital portfolio report.
        """
        records = list(
            self.db.share_capital.find(
                {},
                {
                    "share_id": 1, "member_id": 1, "member_name": 1,
                    "subscribed_shares": 1, "paid_shares": 1,
                    "subscribed_amount": 1, "paid_amount": 1,
                    "outstanding_amount": 1, "percentage_paid": 1,
                    "last_payment_date": 1,
                },
            ).sort("member_id", 1)
        )

        for r in records:
            r.pop("_id", None)
            val = r.get("last_payment_date")
            if isinstance(val, datetime):
                r["last_payment_date"] = val.isoformat()

        # Aggregate totals
        pipeline = [
            {
                "$group": {
                    "_id": None,
                    "total_subscribed": {"$sum": "$subscribed_amount"},
                    "total_paid": {"$sum": "$paid_amount"},
                    "total_outstanding": {"$sum": "$outstanding_amount"},
                    "members_with_shares": {
                        "$sum": {"$cond": [{"$gt": ["$paid_shares", 0]}, 1, 0]}
                    },
                }
            }
        ]
        agg = next(self.db.share_capital.aggregate(pipeline), {})

        return {
            "total_members": len(records),
            "members_with_paid_shares": agg.get("members_with_shares", 0),
            "total_subscribed_amount": round(agg.get("total_subscribed", 0), 2),
            "total_paid_amount": round(agg.get("total_paid", 0), 2),
            "total_outstanding_amount": round(agg.get("total_outstanding", 0), 2),
            "records": records,
        }

    def dashboard_summary(self) -> dict:
        """
        Top-level KPIs for the admin dashboard home page.
        Single aggregation pass across all collections.
        """
        now = utcnow()

        total_members = self.db.members.count_documents({})
        active_members = self.db.members.count_documents({"status": "Active"})

        total_loans = self.db.loans.count_documents({})
        active_loans = self.db.loans.count_documents(
            {"status": {"$in": ["Current", "Past Due"]}}
        )
        past_due_loans = self.db.loans.count_documents({"status": "Past Due"})
        pending_loans = self.db.loans.count_documents({"status": "Pending"})

        # Total outstanding loan portfolio
        loan_agg = next(
            self.db.loans.aggregate([
                {"$match": {"status": {"$in": ["Current", "Past Due"]}}},
                {"$group": {"_id": None, "total": {"$sum": "$outstanding_balance"}}},
            ]),
            {"total": 0},
        )

        # Total savings deposits
        savings_agg = next(
            self.db.savings_accounts.aggregate([
                {"$match": {"status": "Active"}},
                {"$group": {"_id": None, "total": {"$sum": "$current_balance"}}},
            ]),
            {"total": 0},
        )

        # Total share capital paid up
        shares_agg = next(
            self.db.share_capital.aggregate([
                {"$group": {"_id": None, "total": {"$sum": "$paid_amount"}}},
            ]),
            {"total": 0},
        )

        return {
            "as_of": now.isoformat(),
            "members": {
                "total": total_members,
                "active": active_members,
            },
            "loans": {
                "total": total_loans,
                "active": active_loans,
                "past_due": past_due_loans,
                "pending_approval": pending_loans,
                "total_outstanding": round(loan_agg["total"], 2),
            },
            "savings": {
                "total_deposits": round(savings_agg["total"], 2),
            },
            "share_capital": {
                "total_paid_up": round(shares_agg["total"], 2),
            },
        }