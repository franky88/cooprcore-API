# backend/app/services/savings_service.py
import math
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from bson import ObjectId
from bson.errors import InvalidId

from ..utils import utcnow

from ..extensions import mongo
from ..utils.id_generator import generate_account_id, generate_transaction_id
from ..schemas.savings_schema import (
    OpenAccountSchema,
    TransactionSchema,
    PostInterestSchema,
    UpdateAccountSchema,
)
from ..middleware.audit_middleware import log_audit

open_schema = OpenAccountSchema()
transaction_schema = TransactionSchema()
interest_schema = PostInterestSchema()
update_schema = UpdateAccountSchema()

# Interest rates by product type (% per annum)
PRODUCT_RATES: dict[str, float] = {
    "Regular Savings": 3.0,
    "Time Deposit": 5.0,
    "Special Savings": 4.0,
}

# Withholding tax on interest income (Philippine regulation)
WITHHOLDING_TAX_RATE = 0.20

# Months of inactivity before an account is considered dormant
DORMANCY_MONTHS = 12

_PROJECT_SAFE = {
    "_id": 1, "account_id": 1, "member_id": 1, "member_name": 1,
    "product_type": 1, "status": 1, "current_balance": 1, "interest_rate": 1,
    "maturity_date": 1, "placement_amount": 1, "date_opened": 1,
    "last_transaction_date": 1, "last_interest_posting": 1,
    "passbook_number": 1, "created_at": 1, "updated_at": 1,
}


class SavingsService:

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
        for field in ("date_opened", "maturity_date", "last_transaction_date",
                      "last_interest_posting", "created_at", "updated_at"):
            val = doc.get(field)
            if isinstance(val, (datetime, date)):
                doc[field] = val.isoformat()
        return doc

    def _serialize_txn(self, doc: dict | None) -> dict | None:
        if doc is None:
            return None
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        for field in ("transaction_date", "created_at"):
            val = doc.get(field)
            if isinstance(val, (datetime, date)):
                doc[field] = val.isoformat()
        return doc

    # ------------------------------------------------------------------ #
    # Read
    # ------------------------------------------------------------------ #

    def get_accounts(
        self,
        page: int = 1,
        per_page: int = 20,
        member_id: str | None = None,
        product_type: str | None = None,
        status: str | None = None,
    ) -> dict:
        per_page = min(per_page, 100)
        query: dict = {}
        if member_id:
            query["member_id"] = member_id
        if product_type:
            query["product_type"] = product_type
        if status:
            query["status"] = status

        total = self.db.savings_accounts.count_documents(query)
        docs = list(
            self.db.savings_accounts.find(query, _PROJECT_SAFE)
            .sort("date_opened", -1)
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

    def get_by_account_id(self, account_id: str) -> dict | None:
        doc = self.db.savings_accounts.find_one({"account_id": account_id}, _PROJECT_SAFE)
        return self._serialize(doc)

    def get_ledger(
        self,
        account_id: str,
        page: int = 1,
        per_page: int = 50,
    ) -> dict | None:
        """Returns paginated transaction history for an account."""
        account = self.get_by_account_id(account_id)
        if not account:
            return None

        per_page = min(per_page, 200)
        query = {"account_id": account_id}
        total = self.db.savings_transactions.count_documents(query)
        txns = list(
            self.db.savings_transactions.find(query)
            .sort("transaction_date", -1)
            .skip((page - 1) * per_page)
            .limit(per_page)
        )

        return {
            "account": account,
            "data": [self._serialize_txn(t) for t in txns],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": math.ceil(total / per_page) if total else 0,
            },
        }

    # ------------------------------------------------------------------ #
    # Open account
    # ------------------------------------------------------------------ #

    def open_account(self, data: dict, opened_by: str) -> dict:
        errors = open_schema.validate(data)
        if errors:
            return {"error": errors}

        cleaned = open_schema.load(data)
        member_id = cleaned["member_id"]
        product_type = cleaned["product_type"]

        # Member must exist and be Active
        member = self.db.members.find_one({"member_id": member_id})
        if not member:
            return {"error": "Member not found"}
        if member.get("status") != "Active":
            return {"error": f"Member is not Active (status: {member.get('status')})"}

        now = utcnow()
        account_id = generate_account_id(self.db)
        interest_rate = PRODUCT_RATES.get(product_type, 3.0)

        # Compute maturity date for Time Deposits
        maturity_date = None
        if product_type == "Time Deposit" and cleaned.get("term_months"):
            maturity_date = now + relativedelta(months=cleaned["term_months"])

        initial_deposit = cleaned.get("initial_deposit", 0.0)
        member_name = (
            f"{member.get('first_name', '')} {member.get('last_name', '')}".strip()
        )

        account_doc = {
            "account_id": account_id,
            "member_id": member_id,
            "member_name": member_name,
            "product_type": product_type,
            "status": "Active",
            "current_balance": initial_deposit,
            "interest_rate": interest_rate,
            "maturity_date": maturity_date,
            "placement_amount": cleaned.get("placement_amount"),
            "date_opened": now,
            "last_transaction_date": now if initial_deposit > 0 else None,
            "last_interest_posting": None,
            "passbook_number": cleaned.get("passbook_number"),
            "created_at": now,
            "updated_at": now,
        }

        self.db.savings_accounts.insert_one(account_doc)

        # Record the initial deposit as a transaction if > 0
        if initial_deposit > 0:
            self._write_transaction(
                account_id=account_id,
                member_id=member_id,
                transaction_type="Deposit",
                amount=initial_deposit,
                balance_before=0.0,
                balance_after=initial_deposit,
                payment_method="Cash",
                or_number="INITIAL",
                posted_by=opened_by,
                remarks="Initial deposit on account opening",
                transaction_date=now,
            )

        log_audit(
            action="OPEN_SAVINGS_ACCOUNT",
            resource="savings_accounts",
            resource_id=account_id,
            details={"member_id": member_id, "product_type": product_type,
                     "initial_deposit": initial_deposit},
        )

        return self.get_by_account_id(account_id)

    # ------------------------------------------------------------------ #
    # Update account metadata
    # ------------------------------------------------------------------ #

    def update_account(self, account_id: str, data: dict, updated_by: str) -> dict:
        errors = update_schema.validate(data)
        if errors:
            return {"error": errors}

        account = self.db.savings_accounts.find_one({"account_id": account_id})
        if not account:
            return {"error": "Account not found"}

        cleaned = update_schema.load(data)
        if not cleaned:
            return {"error": "No valid fields provided for update"}

        cleaned["updated_at"] = utcnow()
        self.db.savings_accounts.update_one(
            {"account_id": account_id}, {"$set": cleaned}
        )

        log_audit(
            action="UPDATE_SAVINGS_ACCOUNT",
            resource="savings_accounts",
            resource_id=account_id,
            details={"updated_by": updated_by, "fields": list(cleaned.keys())},
        )

        return self.get_by_account_id(account_id)

    # ------------------------------------------------------------------ #
    # Post transaction (deposit or withdrawal)
    # ------------------------------------------------------------------ #

    def post_transaction(
        self, account_id: str, data: dict, posted_by: str
    ) -> dict:
        errors = transaction_schema.validate(data)
        if errors:
            return {"error": errors}

        cleaned = transaction_schema.load(data)

        # Fetch account — use find_one without projection so we have the balance
        account = self.db.savings_accounts.find_one({"account_id": account_id})
        if not account:
            return {"error": "Account not found"}

        # ---- Account state checks ----
        if account["status"] == "Closed":
            return {"error": "Transactions cannot be posted on a Closed account"}
        if account["status"] == "Dormant":
            return {
                "error": "Account is Dormant. It must be reactivated before "
                         "transactions can be posted."
            }

        # ---- Member must be Active ----
        member = self.db.members.find_one({"member_id": account["member_id"]})
        if not member or member.get("status") != "Active":
            return {"error": "Member is not Active. Transaction not permitted."}

        transaction_type = cleaned["transaction_type"]
        amount = cleaned["amount"]
        balance_before = account["current_balance"]

        # ---- Withdrawal guard ----
        if transaction_type == "Withdrawal":
            if amount > balance_before:
                return {
                    "error": f"Insufficient balance. "
                             f"Available: ₱{balance_before:,.2f}, "
                             f"Requested: ₱{amount:,.2f}"
                }

        balance_after = (
            balance_before + amount
            if transaction_type == "Deposit"
            else balance_before - amount
        )
        balance_after = round(balance_after, 2)

        txn_date_raw = cleaned.get("transaction_date")
        txn_date = (
            datetime.combine(txn_date_raw, datetime.min.time())
            if txn_date_raw
            else utcnow()
        )

        txn_id = self._write_transaction(
            account_id=account_id,
            member_id=account["member_id"],
            transaction_type=transaction_type,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            payment_method=cleaned["payment_method"],
            or_number=cleaned["or_number"],
            reference_number=cleaned.get("reference_number"),
            posted_by=posted_by,
            remarks=cleaned.get("remarks", ""),
            transaction_date=txn_date,
        )

        # ---- Update account balance and dormancy tracking ----
        self.db.savings_accounts.update_one(
            {"account_id": account_id},
            {
                "$set": {
                    "current_balance": balance_after,
                    "last_transaction_date": txn_date,
                    "updated_at": utcnow(),
                }
            },
        )

        log_audit(
            action=f"SAVINGS_{transaction_type.upper()}",
            resource="savings_accounts",
            resource_id=account_id,
            details={
                "transaction_id": txn_id,
                "amount": amount,
                "balance_after": balance_after,
                "posted_by": posted_by,
            },
        )

        return {
            "transaction_id": txn_id,
            "account_id": account_id,
            "transaction_type": transaction_type,
            "amount": amount,
            "balance_before": balance_before,
            "balance_after": balance_after,
            "or_number": cleaned["or_number"],
        }

    # ------------------------------------------------------------------ #
    # Post interest
    # ------------------------------------------------------------------ #

    def post_interest(self, data: dict, posted_by: str) -> dict:
        """
        Posts monthly interest to one account (by account_id) or all
        active accounts of a given product_type.

        Rules enforced:
        - Dormant accounts are skipped.
        - Time Deposits: interest is posted only at maturity.
        - 20% withholding tax is deducted from gross interest.
        - Each account can only receive interest once per calendar month.
        """
        errors = interest_schema.validate(data)
        if errors:
            return {"error": errors}

        cleaned = interest_schema.load(data)

        as_of_raw = cleaned.get("as_of_date")
        as_of = (
            datetime.combine(as_of_raw, datetime.min.time())
            if as_of_raw
            else utcnow()
        )

        # Determine which accounts to process
        if cleaned.get("account_id"):
            accounts = list(self.db.savings_accounts.find(
                {"account_id": cleaned["account_id"]}
            ))
        elif cleaned.get("product_type"):
            accounts = list(self.db.savings_accounts.find(
                {"product_type": cleaned["product_type"], "status": "Active"}
            ))
        else:
            # Process all active non-time-deposit accounts
            accounts = list(self.db.savings_accounts.find(
                {"status": "Active",
                 "product_type": {"$in": ["Regular Savings", "Special Savings"]}}
            ))

        results = {"processed": 0, "skipped": 0, "details": []}

        for acct in accounts:
            outcome = self._post_interest_to_account(acct, as_of, posted_by)
            if outcome.get("skipped"):
                results["skipped"] += 1
            else:
                results["processed"] += 1
            results["details"].append(outcome)

        log_audit(
            action="POST_INTEREST",
            resource="savings_accounts",
            resource_id=cleaned.get("account_id") or cleaned.get("product_type") or "ALL",
            details={"processed": results["processed"], "skipped": results["skipped"]},
        )

        return results

    def _post_interest_to_account(
        self, acct: dict, as_of: datetime, posted_by: str
    ) -> dict:
        account_id = acct["account_id"]

        # Skip dormant and closed accounts
        if acct["status"] in ("Dormant", "Closed"):
            return {"account_id": account_id, "skipped": True,
                    "reason": f"Account is {acct['status']}"}

        # Skip if interest already posted this calendar month
        last_posting = acct.get("last_interest_posting")
        if last_posting:
            if (last_posting.year == as_of.year
                    and last_posting.month == as_of.month):
                return {"account_id": account_id, "skipped": True,
                        "reason": "Interest already posted this month"}

        # Time Deposit: only post at maturity
        if acct["product_type"] == "Time Deposit":
            maturity = acct.get("maturity_date")
            if not maturity or as_of < maturity:
                return {"account_id": account_id, "skipped": True,
                        "reason": "Time Deposit has not yet matured"}

        balance = acct["current_balance"]
        if balance <= 0:
            return {"account_id": account_id, "skipped": True,
                    "reason": "Zero balance — no interest to post"}

        # Compute gross interest: balance × rate / 12
        monthly_rate = acct["interest_rate"] / 100 / 12
        gross_interest = round(balance * monthly_rate, 2)

        # Deduct 20% withholding tax
        tax = round(gross_interest * WITHHOLDING_TAX_RATE, 2)
        net_interest = round(gross_interest - tax, 2)

        if net_interest <= 0:
            return {"account_id": account_id, "skipped": True,
                    "reason": "Net interest after tax is zero"}

        balance_after = round(balance + net_interest, 2)

        txn_id = self._write_transaction(
            account_id=account_id,
            member_id=acct["member_id"],
            transaction_type="Interest",
            amount=net_interest,
            balance_before=balance,
            balance_after=balance_after,
            payment_method="System",
            or_number=f"INT-{as_of.strftime('%Y%m')}",
            posted_by=posted_by,
            remarks=f"Monthly interest. Gross: ₱{gross_interest:.2f}, "
                    f"Tax (20%): ₱{tax:.2f}, Net: ₱{net_interest:.2f}",
            transaction_date=as_of,
        )

        self.db.savings_accounts.update_one(
            {"account_id": account_id},
            {
                "$set": {
                    "current_balance": balance_after,
                    "last_interest_posting": as_of,
                    "updated_at": utcnow(),
                }
            },
        )

        return {
            "account_id": account_id,
            "skipped": False,
            "gross_interest": gross_interest,
            "tax_withheld": tax,
            "net_interest": net_interest,
            "balance_after": balance_after,
            "transaction_id": txn_id,
        }

    # ------------------------------------------------------------------ #
    # Dormancy check (can be called by a scheduled job)
    # ------------------------------------------------------------------ #

    def mark_dormant_accounts(self) -> dict:
        """
        Marks accounts as Dormant if last_transaction_date is older than
        DORMANCY_MONTHS and they are currently Active.
        Returns a count of accounts updated.
        """
        cutoff = utcnow() - relativedelta(months=DORMANCY_MONTHS)
        result = self.db.savings_accounts.update_many(
            {
                "status": "Active",
                "last_transaction_date": {"$lt": cutoff},
            },
            {
                "$set": {
                    "status": "Dormant",
                    "updated_at": utcnow(),
                }
            },
        )
        log_audit(
            action="MARK_DORMANT_ACCOUNTS",
            resource="savings_accounts",
            resource_id="BATCH",
            details={"accounts_marked": result.modified_count},
        )
        return {"accounts_marked_dormant": result.modified_count}

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _write_transaction(
        self,
        account_id: str,
        member_id: str,
        transaction_type: str,
        amount: float,
        balance_before: float,
        balance_after: float,
        payment_method: str,
        or_number: str,
        posted_by: str,
        remarks: str = "",
        transaction_date: datetime | None = None,
        reference_number: str | None = None,
    ) -> str:
        """Inserts a savings_transactions document and returns the transaction_id."""
        txn_id = generate_transaction_id(self.db)
        now = utcnow()
        self.db.savings_transactions.insert_one(
            {
                "transaction_id": txn_id,
                "account_id": account_id,
                "member_id": member_id,
                "transaction_type": transaction_type,
                "amount": amount,
                "balance_before": round(balance_before, 2),
                "balance_after": round(balance_after, 2),
                "reference_number": reference_number,
                "or_number": or_number,
                "payment_method": payment_method,
                "posted_by": posted_by,
                "transaction_date": transaction_date or now,
                "remarks": remarks,
                "created_at": now,
            }
        )
        return txn_id