# backend/app/services/member_service.py
import math
from datetime import datetime, date
from bson import ObjectId
from bson.errors import InvalidId

from ..extensions import mongo
from ..utils.id_generator import (
    generate_member_id,
    generate_account_id,
    generate_share_id,
)
from ..schemas.member_schema import CreateMemberSchema, UpdateMemberSchema
from ..middleware.audit_middleware import log_audit
from ..utils import utcnow

create_schema = CreateMemberSchema()
update_schema = UpdateMemberSchema()

# Projection used on all read queries — never expose internal Mongo fields
# we don't want to accidentally leak.
_PROJECT_SAFE = {"password_hash": 0}


class MemberService:

    @property
    def db(self):
        return mongo.db

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #

    def _serialize(self, doc: dict | None) -> dict | None:
        if doc is None:
            return None
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        # Convert date/datetime objects to ISO strings for JSON transport
        for field in ("date_of_birth", "date_admitted", "created_at", "updated_at"):
            val = doc.get(field)
            if isinstance(val, (datetime, date)):
                doc[field] = val.isoformat()
        return doc

    # ------------------------------------------------------------------ #
    # Read
    # ------------------------------------------------------------------ #

    def get_members(
        self,
        page: int = 1,
        per_page: int = 20,
        status: str | None = None,
        membership_type: str | None = None,
        search: str | None = None,
    ) -> dict:
        per_page = min(per_page, 100)
        query: dict = {}

        if status:
            query["status"] = status
        if membership_type:
            query["membership_type"] = membership_type
        if search:
            query["$or"] = [
                {"first_name": {"$regex": search, "$options": "i"}},
                {"last_name": {"$regex": search, "$options": "i"}},
                {"member_id": {"$regex": search, "$options": "i"}},
                {"phone": {"$regex": search, "$options": "i"}},
                {"email": {"$regex": search, "$options": "i"}},
            ]

        total = self.db.members.count_documents(query)
        docs = list(
            self.db.members.find(query, _PROJECT_SAFE)
            .sort([("last_name", 1), ("first_name", 1)])
            .skip((page - 1) * per_page)
            .limit(per_page)
        )

        return {
            "data": [self._serialize(d) for d in docs],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": math.ceil(total / per_page) if total else 0,
            },
        }

    def get_by_member_id(self, member_id: str) -> dict | None:
        doc = self.db.members.find_one({"member_id": member_id}, _PROJECT_SAFE)
        return self._serialize(doc)

    def get_member_summary(self, member_id: str) -> dict | None:
        """
        Returns the member's full profile plus a lightweight summary of
        their active loans, savings accounts, and share capital record.
        """
        member = self.get_by_member_id(member_id)
        if not member:
            return None

        active_loan_statuses = ["Current", "Past Due", "Approved", "Released"]
        loans = list(
            self.db.loans.find(
                {"member_id": member_id, "status": {"$in": active_loan_statuses}},
                {
                    "loan_id": 1,
                    "loan_type": 1,
                    "principal": 1,
                    "outstanding_balance": 1,
                    "monthly_amortization": 1,
                    "status": 1,
                    "maturity_date": 1,
                },
            )
        )

        savings = list(
            self.db.savings_accounts.find(
                {"member_id": member_id, "status": "Active"},
                {
                    "account_id": 1,
                    "product_type": 1,
                    "current_balance": 1,
                    "interest_rate": 1,
                },
            )
        )

        shares = self.db.share_capital.find_one(
            {"member_id": member_id},
            {
                "share_id": 1,
                "subscribed_shares": 1,
                "paid_shares": 1,
                "paid_amount": 1,
                "outstanding_amount": 1,
                "percentage_paid": 1,
            },
        )

        return {
            "member": member,
            "loans": [self._serialize(l) for l in loans],
            "savings": [self._serialize(s) for s in savings],
            "shares": self._serialize(shares) if shares else None,
            "totals": {
                "total_outstanding_loans": sum(
                    l.get("outstanding_balance", 0) for l in loans
                ),
                "total_savings_balance": sum(
                    s.get("current_balance", 0) for s in savings
                ),
                "active_loan_count": len(loans),
            },
        }

    # ------------------------------------------------------------------ #
    # Create
    # ------------------------------------------------------------------ #

    def create_member(self, data: dict, created_by: str) -> dict:
        errors = create_schema.validate(data)
        if errors:
            return {"error": errors}

        cleaned = create_schema.load(data)

        # Uniqueness checks
        if self.db.members.find_one({"phone": cleaned["phone"]}):
            return {"error": {"phone": ["Phone number is already registered"]}}

        if cleaned.get("email") and self.db.members.find_one({"email": cleaned["email"]}):
            return {"error": {"email": ["Email address is already registered"]}}

        member_id = generate_member_id(self.db)
        now = utcnow()

        # Convert date_of_birth (Python date) to datetime for MongoDB
        dob = cleaned.get("date_of_birth")
        if isinstance(dob, date) and not isinstance(dob, datetime):
            cleaned["date_of_birth"] = datetime.combine(dob, datetime.min.time())

        member_doc = {
            **cleaned,
            "member_id": member_id,
            "status": "Active",
            "date_admitted": now,
            "admitting_officer": created_by,
            "photo_url": None,
            "signature_url": None,
            "created_at": now,
            "updated_at": now,
        }

        self.db.members.insert_one(member_doc)

        # Auto-provision a Regular Savings account and a Share Capital record
        self._provision_savings_account(member_id, self._full_name(cleaned))
        self._provision_share_capital(member_id, self._full_name(cleaned))

        log_audit(
            action="CREATE_MEMBER",
            resource="members",
            resource_id=member_id,
            details={"created_by": created_by},
        )

        return self.get_by_member_id(member_id)

    # ------------------------------------------------------------------ #
    # Update
    # ------------------------------------------------------------------ #

    def update_member(self, member_id: str, data: dict, updated_by: str) -> dict:
        errors = update_schema.validate(data)
        if errors:
            return {"error": errors}

        existing = self.get_by_member_id(member_id)
        if not existing:
            return {"error": "Member not found"}

        cleaned = update_schema.load(data)

        # Phone uniqueness: only check if phone is being changed
        new_phone = cleaned.get("phone")
        if new_phone and new_phone != existing.get("phone"):
            if self.db.members.find_one(
                {"phone": new_phone, "member_id": {"$ne": member_id}}
            ):
                return {"error": {"phone": ["Phone number is already registered"]}}

        # Email uniqueness: only check if email is being changed
        new_email = cleaned.get("email")
        if new_email and new_email != existing.get("email"):
            if self.db.members.find_one(
                {"email": new_email, "member_id": {"$ne": member_id}}
            ):
                return {"error": {"email": ["Email address is already registered"]}}

        # Convert date objects for MongoDB
        dob = cleaned.get("date_of_birth")
        if isinstance(dob, date) and not isinstance(dob, datetime):
            cleaned["date_of_birth"] = datetime.combine(dob, datetime.min.time())

        cleaned["updated_at"] = utcnow(),

        self.db.members.update_one({"member_id": member_id}, {"$set": cleaned})

        # Keep denormalized member_name in sync across related collections
        if "first_name" in cleaned or "last_name" in cleaned:
            # Re-fetch to get the current full name after update
            updated = self.get_by_member_id(member_id)
            if updated:
                new_name = self._full_name(updated)
                self._sync_member_name(member_id, new_name)

        log_audit(
            action="UPDATE_MEMBER",
            resource="members",
            resource_id=member_id,
            details={"updated_by": updated_by, "fields": list(cleaned.keys())},
        )

        return self.get_by_member_id(member_id)

    # ------------------------------------------------------------------ #
    # Business rule checks (used by other services)
    # ------------------------------------------------------------------ #

    def assert_member_active(self, member_id: str) -> dict | None:
        """
        Returns None if the member is Active.
        Returns an error dict if not found or not Active.
        Other services call this before any transaction.
        """
        member = self.get_by_member_id(member_id)
        if not member:
            return {"error": "Member not found"}
        if member["status"] != "Active":
            return {
                "error": f"Member is not Active (current status: {member['status']}). "
                         "Transactions are not permitted."
            }
        return None

    def count_active_loans(self, member_id: str) -> int:
        """Used by LoanService to enforce the 2-loan maximum rule."""
        return self.db.loans.count_documents(
            {
                "member_id": member_id,
                "status": {"$in": ["Approved", "Released", "Current", "Past Due"]},
            }
        )

    def has_past_due_loan(self, member_id: str) -> bool:
        """Used by LoanService to enforce good-standing requirement."""
        return (
            self.db.loans.count_documents(
                {"member_id": member_id, "status": "Past Due"}
            )
            > 0
        )

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _full_name(self, doc: dict) -> str:
        parts = [
            doc.get("first_name", ""),
            doc.get("middle_name", ""),
            doc.get("last_name", ""),
            doc.get("suffix", ""),
        ]
        return " ".join(p for p in parts if p).strip()

    def _provision_savings_account(self, member_id: str, member_name: str) -> None:
        now = utcnow(),
        self.db.savings_accounts.insert_one(
            {
                "account_id": generate_account_id(self.db),
                "member_id": member_id,
                "member_name": member_name,
                "product_type": "Regular Savings",
                "status": "Active",
                "current_balance": 0.0,
                "interest_rate": 3.0,
                "maturity_date": None,
                "placement_amount": None,
                "date_opened": now,
                "last_transaction_date": None,
                "last_interest_posting": None,
                "passbook_number": None,
                "created_at": now,
                "updated_at": now,
            }
        )

    def _provision_share_capital(self, member_id: str, member_name: str) -> None:
        now = utcnow(),
        self.db.share_capital.insert_one(
            {
                "share_id": generate_share_id(self.db),
                "member_id": member_id,
                "member_name": member_name,
                "subscribed_shares": 0,
                "paid_shares": 0,
                "share_par_value": 100.0,
                "subscribed_amount": 0.0,
                "paid_amount": 0.0,
                "outstanding_amount": 0.0,
                "percentage_paid": 0.0,
                "date_subscribed": now,
                "last_payment_date": None,
                "created_at": now,
                "updated_at": now,
            }
        )

    def _sync_member_name(self, member_id: str, new_name: str) -> None:
        """
        Propagates a name change to all collections that store
        the denormalized member_name field.
        """
        update = {"$set": {"member_name": new_name}}
        self.db.loans.update_many({"member_id": member_id}, update)
        self.db.savings_accounts.update_many({"member_id": member_id}, update)
        self.db.share_capital.update_many({"member_id": member_id}, update)

    
    def deactivate_member(self, member_id: str, updated_by: str) -> dict:
        member = self.db.members.find_one({"member_id": member_id})
        if not member:
            return {"error": "Member not found"}

        if member.get("status") == "Inactive":
            return {"error": "Member is already inactive"}

        active_loans = self.db.loans.count_documents(
            {
                "member_id": member_id,
                "status": {"$in": ["Approved", "Released", "Current", "Past Due"]},
            }
        )
        if active_loans > 0:
            return {
                "error": "Member cannot be deactivated while there are active or unsettled loans"
            }

        self.db.members.update_one(
            {"member_id": member_id},
            {
                "$set": {
                    "status": "Inactive",
                    "updated_at": utcnow(),
                }
            },
        )

        log_audit(
            action="DEACTIVATE_MEMBER",
            resource="members",
            resource_id=member_id,
            details={"updated_by": updated_by},
        )

        return self.get_by_member_id(member_id)