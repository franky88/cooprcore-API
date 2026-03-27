# backend/app/services/share_service.py
import math
from datetime import datetime, date

from ..extensions import mongo
from ..utils.id_generator import (
    generate_share_id,
    generate_share_payment_id,
    generate_dividend_id,
)
from ..utils import utcnow
from ..schemas.share_schema import (
    UpdateSubscriptionSchema,
    RecordPaymentSchema,
    DividendSchema,
    PAR_VALUE,
)
from ..middleware.audit_middleware import log_audit

subscription_schema = UpdateSubscriptionSchema()
payment_schema = RecordPaymentSchema()
dividend_schema = DividendSchema()

_PROJECT_SAFE = {
    "_id": 1, "share_id": 1, "member_id": 1, "member_name": 1,
    "subscribed_shares": 1, "paid_shares": 1, "share_par_value": 1,
    "subscribed_amount": 1, "paid_amount": 1, "outstanding_amount": 1,
    "percentage_paid": 1, "date_subscribed": 1, "last_payment_date": 1,
    "created_at": 1, "updated_at": 1,
}


class ShareService:

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
        for field in ("date_subscribed", "last_payment_date", "created_at", "updated_at"):
            val = doc.get(field)
            if isinstance(val, (datetime, date)):
                doc[field] = val.isoformat()
        return doc

    def _serialize_payment(self, doc: dict | None) -> dict | None:
        if doc is None:
            return None
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        for field in ("payment_date", "created_at"):
            val = doc.get(field)
            if isinstance(val, (datetime, date)):
                doc[field] = val.isoformat()
        return doc

    # ------------------------------------------------------------------ #
    # Read
    # ------------------------------------------------------------------ #

    def get_shares(
        self,
        page: int = 1,
        per_page: int = 20,
        member_id: str | None = None,
        search: str | None = None,
    ) -> dict:
        per_page = min(per_page, 100)
        query: dict = {}
        if member_id:
            query["member_id"] = member_id
        if search:
            query["$or"] = [
                {"member_name": {"$regex": search, "$options": "i"}},
                {"member_id": {"$regex": search, "$options": "i"}},
                {"share_id": {"$regex": search, "$options": "i"}},
            ]

        total = self.db.share_capital.count_documents(query)
        docs = list(
            self.db.share_capital.find(query, _PROJECT_SAFE)
            .sort("member_id", 1)
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

    def get_by_share_id(self, share_id: str) -> dict | None:
        doc = self.db.share_capital.find_one({"share_id": share_id}, _PROJECT_SAFE)
        return self._serialize(doc)

    def get_by_member_id(self, member_id: str) -> dict | None:
        doc = self.db.share_capital.find_one({"member_id": member_id}, _PROJECT_SAFE)
        return self._serialize(doc)

    def get_payments(self, share_id: str) -> dict | None:
        """Returns full payment history for a share record."""
        record = self.get_by_share_id(share_id)
        if not record:
            return None

        payments = list(
            self.db.share_payments.find(
                {"share_id": share_id}, {"_id": 1, "payment_id": 1, "share_id": 1,
                                          "member_id": 1, "shares_paid": 1,
                                          "amount_paid": 1, "balance_after": 1,
                                          "or_number": 1, "payment_date": 1,
                                          "posted_by": 1, "remarks": 1, "created_at": 1}
            ).sort("payment_date", 1)
        )
        return {
            "share_record": record,
            "payments": [self._serialize_payment(p) for p in payments],
        }

    # ------------------------------------------------------------------ #
    # Update subscription
    # ------------------------------------------------------------------ #

    def update_subscription(
        self, share_id: str, data: dict, updated_by: str
    ) -> dict:
        errors = subscription_schema.validate(data)
        if errors:
            return {"error": errors}

        cleaned = subscription_schema.load(data)
        record = self.db.share_capital.find_one({"share_id": share_id})
        if not record:
            return {"error": "Share record not found"}

        # ---- Member must be Active ----
        member = self.db.members.find_one({"member_id": record["member_id"]})
        if not member or member.get("status") != "Active":
            return {"error": "Member is not Active. Subscription update not permitted."}

        additional_shares = cleaned["additional_shares"]
        additional_amount = additional_shares * PAR_VALUE

        new_subscribed_shares = record["subscribed_shares"] + additional_shares
        new_subscribed_amount = record["subscribed_amount"] + additional_amount
        new_outstanding = new_subscribed_amount - record["paid_amount"]

        # Recompute percentage
        percentage_paid = (
            round((record["paid_amount"] / new_subscribed_amount) * 100, 2)
            if new_subscribed_amount > 0
            else 0.0
        )

        self.db.share_capital.update_one(
            {"share_id": share_id},
            {
                "$set": {
                    "subscribed_shares": new_subscribed_shares,
                    "subscribed_amount": round(new_subscribed_amount, 2),
                    "outstanding_amount": round(new_outstanding, 2),
                    "percentage_paid": percentage_paid,
                    "updated_at": utcnow(),
                }
            },
        )

        log_audit(
            action="UPDATE_SHARE_SUBSCRIPTION",
            resource="share_capital",
            resource_id=share_id,
            details={
                "additional_shares": additional_shares,
                "new_subscribed_shares": new_subscribed_shares,
                "updated_by": updated_by,
            },
        )

        return self.get_by_share_id(share_id)

    # ------------------------------------------------------------------ #
    # Record payment
    # ------------------------------------------------------------------ #

    def record_payment(self, share_id: str, data: dict, posted_by: str) -> dict:
        errors = payment_schema.validate(data)
        if errors:
            return {"error": errors}

        cleaned = payment_schema.load(data)
        record = self.db.share_capital.find_one({"share_id": share_id})
        if not record:
            return {"error": "Share record not found"}

        # ---- Member must be Active ----
        member = self.db.members.find_one({"member_id": record["member_id"]})
        if not member or member.get("status") != "Active":
            return {"error": "Member is not Active. Payment not permitted."}

        # ---- Must have an active subscription ----
        if record["subscribed_shares"] == 0:
            return {
                "error": "Member has no share subscription. "
                         "Update subscription before recording a payment."
            }

        # ---- Cannot overpay beyond subscribed amount ----
        amount_paid = cleaned["amount_paid"]
        outstanding = record["outstanding_amount"]
        if amount_paid > outstanding:
            return {
                "error": f"Payment of ₱{amount_paid:,.2f} exceeds the outstanding "
                         f"subscription balance of ₱{outstanding:,.2f}."
            }

        # Derive shares paid from amount (always a whole number due to schema validation)
        shares_paid = int(amount_paid / PAR_VALUE)
        new_paid_shares = record["paid_shares"] + shares_paid
        new_paid_amount = round(record["paid_amount"] + amount_paid, 2)
        new_outstanding = round(record["subscribed_amount"] - new_paid_amount, 2)
        percentage_paid = (
            round((new_paid_amount / record["subscribed_amount"]) * 100, 2)
            if record["subscribed_amount"] > 0
            else 0.0
        )

        payment_date_raw = cleaned.get("payment_date")
        payment_date = (
            datetime.combine(payment_date_raw, datetime.min.time())
            if payment_date_raw
            else utcnow()
        )

        # Generate payment ID
        payment_id = generate_share_payment_id(self.db)

        payment_doc = {
            "payment_id": payment_id,
            "share_id": share_id,
            "member_id": record["member_id"],
            "shares_paid": shares_paid,
            "amount_paid": amount_paid,
            "balance_after": new_outstanding,
            "or_number": cleaned["or_number"],
            "payment_date": payment_date,
            "posted_by": posted_by,
            "remarks": cleaned.get("remarks", ""),
            "created_at": utcnow(),
        }

        self.db.share_payments.insert_one(payment_doc)

        # ---- Update share_capital record ----
        self.db.share_capital.update_one(
            {"share_id": share_id},
            {
                "$set": {
                    "paid_shares": new_paid_shares,
                    "paid_amount": new_paid_amount,
                    "outstanding_amount": new_outstanding,
                    "percentage_paid": percentage_paid,
                    "last_payment_date": payment_date,
                    "updated_at": utcnow(),
                }
            },
        )

        log_audit(
            action="RECORD_SHARE_PAYMENT",
            resource="share_capital",
            resource_id=share_id,
            details={
                "payment_id": payment_id,
                "amount_paid": amount_paid,
                "shares_paid": shares_paid,
                "posted_by": posted_by,
            },
        )

        return {
            "payment_id": payment_id,
            "share_id": share_id,
            "member_id": record["member_id"],
            "amount_paid": amount_paid,
            "shares_paid": shares_paid,
            "new_paid_shares": new_paid_shares,
            "new_paid_amount": new_paid_amount,
            "outstanding_after": new_outstanding,
            "percentage_paid": percentage_paid,
        }

    # ------------------------------------------------------------------ #
    # Dividend distribution
    # ------------------------------------------------------------------ #

    def distribute_dividends(self, data: dict, declared_by: str) -> dict:
        """
        Computes and records dividends for all members with paid-up shares.

        Dividend = paid_amount × (dividend_rate / 100)

        Rules enforced:
        - Only members with paid_shares > 0 receive a dividend.
        - Each fiscal year can only be processed once (idempotency guard).
        - Dividends are recorded in share_payments with type "Dividend".
        - Dividends do NOT increase paid_shares — they are a cash distribution,
          not a share purchase.
        """
        errors = dividend_schema.validate(data)
        if errors:
            return {"error": errors}

        cleaned = dividend_schema.load(data)
        dividend_rate = cleaned["dividend_rate"]
        fiscal_year = cleaned["fiscal_year"]

        # ---- Idempotency: block duplicate dividend for same fiscal year ----
        existing = self.db.share_payments.find_one(
            {"fiscal_year": fiscal_year, "payment_type": "Dividend"}
        )
        if existing:
            return {
                "error": f"Dividends for fiscal year {fiscal_year} have already "
                         "been distributed."
            }

        eligible = list(
            self.db.share_capital.find({"paid_shares": {"$gt": 0}})
        )

        if not eligible:
            return {"error": "No members with paid-up shares found."}

        results = []
        total_distributed = 0.0
        now = utcnow()

        for record in eligible:
            dividend_amount = round(record["paid_amount"] * (dividend_rate / 100), 2)
            if dividend_amount <= 0:
                continue

            payment_id = generate_dividend_id(self.db, fiscal_year)

            self.db.share_payments.insert_one(
                {
                    "payment_id": payment_id,
                    "share_id": record["share_id"],
                    "member_id": record["member_id"],
                    "payment_type": "Dividend",
                    "fiscal_year": fiscal_year,
                    "dividend_rate": dividend_rate,
                    "shares_paid": 0,        # dividends don't add shares
                    "amount_paid": dividend_amount,
                    "balance_after": record["outstanding_amount"],  # unchanged
                    "or_number": f"DIV-{fiscal_year}",
                    "payment_date": now,
                    "posted_by": declared_by,
                    "remarks": cleaned.get("remarks", "")
                              or f"Dividend at {dividend_rate}% for FY {fiscal_year}",
                    "created_at": now,
                }
            )

            total_distributed += dividend_amount
            results.append(
                {
                    "member_id": record["member_id"],
                    "member_name": record["member_name"],
                    "paid_amount": record["paid_amount"],
                    "dividend_amount": dividend_amount,
                }
            )

        log_audit(
            action="DISTRIBUTE_DIVIDENDS",
            resource="share_capital",
            resource_id=f"FY-{fiscal_year}",
            details={
                "fiscal_year": fiscal_year,
                "dividend_rate": dividend_rate,
                "members_paid": len(results),
                "total_distributed": round(total_distributed, 2),
                "declared_by": declared_by,
            },
        )

        return {
            "fiscal_year": fiscal_year,
            "dividend_rate": dividend_rate,
            "members_paid": len(results),
            "total_distributed": round(total_distributed, 2),
            "breakdown": results,
        }