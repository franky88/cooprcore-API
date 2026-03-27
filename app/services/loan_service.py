# backend/app/services/loan_service.py
import math
from datetime import datetime, date
from pymongo.errors import DuplicateKeyError

from app.utils import utcnow

from ..extensions import mongo
from ..utils.id_generator import generate_loan_id, generate_payment_id
from ..utils.loan_calculator import (
    LOAN_MIN_MEMBERSHIP_MONTHS,
    LOAN_DEFAULT_MIN_MEMBERSHIP_MONTHS,
    compute_amortization,
    compute_maturity_date,
    allocate_payment,
    months_since,
    get_effective_loan_config,
    get_effective_settings,
    compute_payment_state,
)
from ..schemas.loan_schema import (
    LoanApplicationSchema,
    ApprovalSchema,
    RejectionSchema,
    PostPaymentSchema,
    ReleaseSchema,
)
from ..middleware.audit_middleware import log_audit

application_schema = LoanApplicationSchema()
approval_schema = ApprovalSchema()
rejection_schema = RejectionSchema()
payment_schema = PostPaymentSchema()
release_schema = ReleaseSchema()

_PROJECT_SAFE = {
    "_id": 1, "loan_id": 1, "member_id": 1, "member_name": 1,
    "loan_type": 1, "principal": 1, "interest_rate": 1,
    "term_months": 1, "monthly_amortization": 1, "total_payable": 1,
    "total_interest": 1, "outstanding_balance": 1, "total_paid": 1,
    "payments_made": 1, "status": 1, "purpose": 1, "co_makers": 1,
    "collateral": 1, "date_applied": 1, "date_approved": 1,
    "date_released": 1, "maturity_date": 1, "approved_by": 1,
    "approved_at": 1, "rejected_reason": 1, "created_at": 1,
    "updated_at": 1,
}


class LoanService:

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
        for field in (
            "date_applied", "date_approved", "date_released",
            "maturity_date", "approved_at", "created_at", "updated_at",
        ):
            val = doc.get(field)
            if isinstance(val, (datetime, date)):
                doc[field] = val.isoformat()
        return doc

    # ------------------------------------------------------------------ #
    # Read
    # ------------------------------------------------------------------ #

    def get_loans(
        self,
        page: int = 1,
        per_page: int = 20,
        member_id: str | None = None,
        status: str | None = None,
        loan_type: str | None = None,
    ) -> dict:
        per_page = min(per_page, 100)
        query: dict = {}
        if member_id:
            query["member_id"] = member_id
        if status:
            query["status"] = status
        if loan_type:
            query["loan_type"] = loan_type

        total = self.db.loans.count_documents(query)
        docs = list(
            self.db.loans.find(query, _PROJECT_SAFE)
            .sort("date_applied", -1)
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

    def get_by_loan_id(self, loan_id: str) -> dict | None:
        doc = self.db.loans.find_one({"loan_id": loan_id}, _PROJECT_SAFE)
        return self._serialize(doc)

    def get_schedule(self, loan_id: str) -> dict | None:
        """Returns the amortization schedule using the stored loan terms."""
        loan = self.db.loans.find_one({"loan_id": loan_id}, _PROJECT_SAFE)
        if not loan:
            return None

        result = compute_amortization(
            principal=float(loan["principal"]),
            annual_rate=float(loan["interest_rate"]),
            term_months=int(loan["term_months"]),
            release_date=loan.get("date_released"),
        )

        serialized_schedule = []
        for row in result["schedule"]:
            item = dict(row)
            if isinstance(item.get("due_date"), datetime):
                item["due_date"] = item["due_date"].isoformat()
            serialized_schedule.append(item)

        return {
            "loan_id": loan_id,
            "monthly_amortization": result["monthly_amortization"],
            "total_payable": result["total_payable"],
            "total_interest": result["total_interest"],
            "schedule": serialized_schedule,
        }

    def get_payments(self, loan_id: str) -> dict | None:
        loan = self.get_by_loan_id(loan_id)
        if not loan:
            return None
        payments = list(
            self.db.loan_payments.find(
                {"loan_id": loan_id}, {"_id": 0}
            ).sort([("payment_date", 1), ("created_at", 1)])
        )
        for p in payments:
            for f in ("payment_date", "created_at"):
                if isinstance(p.get(f), datetime):
                    p[f] = p[f].isoformat()
        return {"loan_id": loan_id, "payments": payments}

    # ------------------------------------------------------------------ #
    # Apply
    # ------------------------------------------------------------------ #

    def apply(self, data: dict, submitted_by: str) -> dict:
        errors = application_schema.validate(data)
        if errors:
            return {"error": errors}

        cleaned = application_schema.load(data)
        member_id = cleaned["member_id"]
        loan_type = cleaned["loan_type"]
        principal = cleaned["principal"]
        term_months = cleaned["term_months"]

        # ---- Load settings-driven config ----
        loan_type_config = get_effective_loan_config()
        biz_settings = get_effective_settings()

        if loan_type not in loan_type_config:
            return {"error": f"Invalid loan type: {loan_type}"}

        annual_rate = loan_type_config[loan_type]["annual_rate"]
        max_term = loan_type_config[loan_type]["max_term_months"]
        comaker_threshold = biz_settings["comaker_threshold"]
        max_active_loans = biz_settings["max_active_loans"]

        # ---- Fetch member ----
        member = self.db.members.find_one({"member_id": member_id})
        if not member:
            return {"error": "Member not found"}

        # ---- Business rule: member must be Active ----
        if member.get("status") != "Active":
            return {
                "error": f"Member is not Active (status: {member.get('status')}). "
                         "Loan applications are not permitted."
            }

        # ---- Business rule: no past-due loans ----
        if self.db.loans.count_documents(
            {"member_id": member_id, "status": "Past Due"}
        ) > 0:
            return {"error": "Member has past-due loans. Application is not permitted."}

        # ---- Business rule: max active loans (from settings) ----
        active_count = self.db.loans.count_documents(
            {"member_id": member_id,
             "status": {"$in": ["Approved", "Released", "Current", "Past Due"]}}
        )
        if active_count >= max_active_loans:
            return {
                "error": f"Member already has {active_count} active loan(s). "
                         f"Maximum allowed is {max_active_loans}."
            }

        # ---- Business rule: minimum membership age ----
        date_admitted = member.get("date_admitted")
        if date_admitted:
            min_months = LOAN_MIN_MEMBERSHIP_MONTHS.get(
                loan_type, LOAN_DEFAULT_MIN_MEMBERSHIP_MONTHS
            )
            months_member = months_since(date_admitted)
            if months_member < min_months:
                return {
                    "error": f"Member must have been a member for at least "
                             f"{min_months} months to apply for a {loan_type} loan "
                             f"(currently {months_member} month(s))."
                }

        # ---- Business rule: term must not exceed max for loan type (from settings) ----
        if term_months > max_term:
            return {
                "error": f"Maximum term for {loan_type} loans is {max_term} months."
            }

        # ---- Business rule: co-maker required (from settings) ----
        co_makers = cleaned.get("co_makers", [])
        if principal > comaker_threshold and len(co_makers) == 0:
            return {
                "error": f"Loans above ₱{comaker_threshold:,.2f} require at least "
                         "one co-maker."
            }

        # ---- Compute financials ----
        amort = compute_amortization(principal, annual_rate, term_months)

        loan_id = generate_loan_id(self.db)
        now = utcnow()
        member_name = (
            f"{member.get('first_name', '')} {member.get('last_name', '')}".strip()
        )

        loan_doc = {
            "loan_id": loan_id,
            "member_id": member_id,
            "member_name": member_name,
            "loan_type": loan_type,
            "principal": principal,
            "interest_rate": annual_rate,  # ← from settings
            "term_months": term_months,
            "monthly_amortization": amort["monthly_amortization"],
            "total_payable": amort["total_payable"],
            "total_interest": amort["total_interest"],
            "outstanding_balance": principal,
            "total_paid": 0.0,
            "payments_made": 0,
            "status": "Pending",
            "purpose": cleaned["purpose"],
            "co_makers": co_makers,
            "collateral": cleaned.get("collateral"),
            "date_applied": now,
            "date_approved": None,
            "date_released": None,
            "maturity_date": None,
            "approved_by": None,
            "approved_at": None,
            "rejected_reason": None,
            "submitted_by": submitted_by,
            "created_at": now,
            "updated_at": now,
        }

        try:
            self.db.loans.insert_one(loan_doc)
        except DuplicateKeyError:
            return {"error": "A duplicate ID was generated. Please try again."}

        log_audit(
            action="APPLY_LOAN",
            resource="loans",
            resource_id=loan_id,
            details={
                "member_id": member_id,
                "loan_type": loan_type,
                "principal": principal,
                "interest_rate": annual_rate,
            },
        )

        return self.get_by_loan_id(loan_id)

    # ------------------------------------------------------------------ #
    # Approve
    # ------------------------------------------------------------------ #

    def approve(self, loan_id: str, data: dict, approved_by: str) -> dict:
        errors = approval_schema.validate(data)
        if errors:
            return {"error": errors}

        loan = self.db.loans.find_one({"loan_id": loan_id})
        if not loan:
            return {"error": "Loan not found"}
        if loan["status"] != "Pending":
            return {
                "error": f"Only Pending loans can be approved "
                         f"(current: {loan['status']})"
            }

        now = utcnow()
        self.db.loans.update_one(
            {"loan_id": loan_id},
            {
                "$set": {
                    "status": "Approved",
                    "approved_by": approved_by,
                    "approved_at": now,
                    "date_approved": now,
                    "updated_at": now,
                }
            },
        )

        log_audit(
            action="APPROVE_LOAN",
            resource="loans",
            resource_id=loan_id,
            details={"approved_by": approved_by},
        )

        return self.get_by_loan_id(loan_id)

    # ------------------------------------------------------------------ #
    # Reject
    # ------------------------------------------------------------------ #

    def reject(self, loan_id: str, data: dict, rejected_by: str) -> dict:
        errors = rejection_schema.validate(data)
        if errors:
            return {"error": errors}

        loan = self.db.loans.find_one({"loan_id": loan_id})
        if not loan:
            return {"error": "Loan not found"}
        if loan["status"] != "Pending":
            return {
                "error": f"Only Pending loans can be rejected "
                         f"(current: {loan['status']})"
            }

        self.db.loans.update_one(
            {"loan_id": loan_id},
            {
                "$set": {
                    "status": "Rejected",
                    "rejected_reason": data["reason"],
                    "updated_at": utcnow(),
                }
            },
        )

        log_audit(
            action="REJECT_LOAN",
            resource="loans",
            resource_id=loan_id,
            details={"rejected_by": rejected_by, "reason": data["reason"]},
        )

        return self.get_by_loan_id(loan_id)

    # ------------------------------------------------------------------ #
    # Release
    # ------------------------------------------------------------------ #

    def release(self, loan_id: str, data: dict, released_by: str) -> dict:
        errors = release_schema.validate(data)
        if errors:
            return {"error": errors}

        loan = self.db.loans.find_one({"loan_id": loan_id})
        if not loan:
            return {"error": "Loan not found"}
        if loan["status"] != "Approved":
            return {
                "error": f"Only Approved loans can be released "
                         f"(current: {loan['status']})"
            }

        cleaned = release_schema.load(data)
        release_date = cleaned.get("release_date")
        if release_date:
            now = datetime.combine(release_date, datetime.min.time())
        else:
            now = utcnow()
        maturity = compute_maturity_date(now, loan["term_months"])

        self.db.loans.update_one(
            {"loan_id": loan_id},
            {
                "$set": {
                    "status": "Current",
                    "date_released": now,
                    "maturity_date": maturity,
                    "outstanding_balance": loan["principal"],
                    "updated_at": now,
                }
            },
        )

        log_audit(
            action="RELEASE_LOAN",
            resource="loans",
            resource_id=loan_id,
            details={
                "released_by": released_by,
                "or_number": data["or_number"],
                "maturity_date": maturity.isoformat(),
            },
        )

        return self.get_by_loan_id(loan_id)

    # ------------------------------------------------------------------ #
    # Post payment
    # ------------------------------------------------------------------ #

    def post_payment(self, loan_id: str, data: dict, posted_by: str) -> dict:
        errors = payment_schema.validate(data)
        if errors:
            return {"error": errors}

        cleaned = payment_schema.load(data)

        loan = self.db.loans.find_one({"loan_id": loan_id})
        if not loan:
            return {"error": "Loan not found"}

        if loan["status"] not in ("Current", "Past Due"):
            return {
                "error": (
                    "Payments can only be posted on Current or Past Due loans "
                    f"(current: {loan['status']})"
                )
            }

        payment_date_raw = cleaned.get("payment_date")
        payment_dt = (
            datetime.combine(payment_date_raw, datetime.min.time())
            if payment_date_raw
            else utcnow()
        )

        prior_payments = list(
            self.db.loan_payments.find(
                {"loan_id": loan_id},
                {
                    "_id": 0,
                    "principal_portion": 1,
                    "interest_portion": 1,
                    "penalty_portion": 1,
                    "payment_date": 1,
                    "created_at": 1,
                },
            ).sort([("payment_date", 1), ("created_at", 1)])
        )

        biz_settings = get_effective_settings()
        penalty_rate_daily = biz_settings["penalty_rate_monthly"] / 100 / 30

        state_before = compute_payment_state(
            loan=loan,
            prior_payments=prior_payments,
            as_of=payment_dt,
            penalty_rate_daily=penalty_rate_daily,
        )

        if state_before["outstanding_balance"] <= 0:
            return {"error": "Loan is already fully paid"}

        amount_paid = float(cleaned["amount_paid"])

        allocation = allocate_payment(
            amount_paid=amount_paid,
            penalty_due=state_before["penalty_due"],
            interest_due=state_before["interest_due"],
            principal_due=state_before["principal_due"],
        )

        new_balance = round(
            max(state_before["outstanding_balance"] - allocation["principal_portion"], 0.0),
            2,
        )

        payment_id = generate_payment_id(self.db)
        now = utcnow()

        payment_doc = {
            "payment_id": payment_id,
            "loan_id": loan_id,
            "member_id": loan["member_id"],
            "amount_paid": round(amount_paid, 2),
            "principal_portion": allocation["principal_portion"],
            "interest_portion": allocation["interest_portion"],
            "penalty_portion": allocation["penalty_portion"],
            "excess": allocation["excess"],
            "balance_after": new_balance,
            "payment_date": payment_dt,
            "payment_method": cleaned["payment_method"],
            "or_number": cleaned["or_number"],
            "posted_by": posted_by,
            "remarks": cleaned.get("remarks", ""),
            "created_at": now,
            # helpful accounting snapshot fields
            "scheduled_interest_due": state_before["interest_due"],
            "scheduled_principal_due": state_before["principal_due"],
            "penalty_due_before_payment": state_before["penalty_due"],
        }

        self.db.loan_payments.insert_one(payment_doc)

        simulated_payments = prior_payments + [payment_doc]
        state_after = compute_payment_state(
            loan=loan,
            prior_payments=simulated_payments,
            as_of=payment_dt,
            penalty_rate_daily=penalty_rate_daily,
        )

        if new_balance <= 0:
            new_status = "Closed"
        elif state_after["overdue_unpaid_amount"] > 0:
            new_status = "Past Due"
        else:
            new_status = "Current"

        self.db.loans.update_one(
            {"loan_id": loan_id},
            {
                "$set": {
                    "outstanding_balance": new_balance,
                    "status": new_status,
                    "updated_at": now,
                },
                "$inc": {
                    "total_paid": round(amount_paid - allocation["excess"], 2),
                    "payments_made": 1,
                },
            },
        )

        log_audit(
            action="POST_LOAN_PAYMENT",
            resource="loans",
            resource_id=loan_id,
            details={
                "payment_id": payment_id,
                "amount_paid": round(amount_paid, 2),
                "principal_portion": allocation["principal_portion"],
                "interest_portion": allocation["interest_portion"],
                "penalty_portion": allocation["penalty_portion"],
                "excess": allocation["excess"],
                "balance_after": new_balance,
                "posted_by": posted_by,
            },
        )

        next_due_date = state_after.get("next_due_date")
        if isinstance(next_due_date, datetime):
            next_due_date = next_due_date.isoformat()

        return {
            "payment_id": payment_id,
            "loan_id": loan_id,
            "amount_paid": round(amount_paid, 2),
            "penalty_due_before_payment": state_before["penalty_due"],
            "interest_due_before_payment": state_before["interest_due"],
            "principal_due_before_payment": state_before["principal_due"],
            "principal_portion": allocation["principal_portion"],
            "interest_portion": allocation["interest_portion"],
            "penalty_portion": allocation["penalty_portion"],
            "excess": allocation["excess"],
            "balance_after": new_balance,
            "loan_status": new_status,
            "next_due_date": next_due_date,
        }

    # ------------------------------------------------------------------ #
    # Calculator (reads rates from settings)
    # ------------------------------------------------------------------ #

    def calculate(self, loan_type: str, principal: float, term_months: int) -> dict:
        loan_type_config = get_effective_loan_config()

        if loan_type not in loan_type_config:
            return {
                "error": f"Invalid loan type. Valid types: {', '.join(loan_type_config.keys())}"
            }

        config = loan_type_config[loan_type]
        max_term = config["max_term_months"]
        annual_rate = config["annual_rate"]

        if term_months < 1 or term_months > max_term:
            return {
                "error": f"Term for {loan_type} loans must be between 1 and {max_term} months."
            }

        if principal < 1000:
            return {"error": "Minimum loan amount is ₱1,000."}

        result = compute_amortization(principal, annual_rate, term_months)

        return {
            "loan_type": loan_type,
            "principal": principal,
            "annual_rate": annual_rate,
            "term_months": term_months,
            **result,
        }
    
    # ------------------------------------------------------------------ #
    # Past-due automation
    # ------------------------------------------------------------------ #

    def mark_past_due(self) -> dict:
        """
        Scans all Current loans and marks them Past Due if:
          Case 1 — maturity_date has passed.
          Case 2 — next expected payment is more than 30 days overdue
                   (missed payment before maturity is reached).

        Idempotent — loans already Past Due or Closed are never touched.
        Called by the scheduler daily and also via POST /admin/past-due-check.
        """
        from dateutil.relativedelta import relativedelta

        now = utcnow()
        marked = 0
        details = []

        # ---- Case 1: maturity date passed ----
        overdue_maturity = list(
            self.db.loans.find(
                {
                    "status": "Current",
                    "maturity_date": {"$lt": now},
                },
                {
                    "loan_id": 1, "member_id": 1, "member_name": 1,
                    "maturity_date": 1, "outstanding_balance": 1,
                },
            )
        )

        for loan in overdue_maturity:
            days_overdue = (now - loan["maturity_date"]).days
            self.db.loans.update_one(
                {"loan_id": loan["loan_id"]},
                {"$set": {"status": "Past Due", "updated_at": now}},
            )
            marked += 1
            details.append({
                "loan_id": loan["loan_id"],
                "member_id": loan["member_id"],
                "member_name": loan["member_name"],
                "reason": "maturity_date_passed",
                "days_overdue": days_overdue,
                "outstanding_balance": loan["outstanding_balance"],
            })
            log_audit(
                action="AUTO_MARK_PAST_DUE",
                resource="loans",
                resource_id=loan["loan_id"],
                details={"reason": "maturity_date_passed", "days_overdue": days_overdue},
            )

        # ---- Case 2: missed payment (maturity not yet reached) ----
        current_loans = list(
            self.db.loans.find(
                {
                    "status": "Current",
                    "maturity_date": {"$gte": now},
                    "date_released": {"$exists": True, "$ne": None},
                },
                {
                    "loan_id": 1, "member_id": 1, "member_name": 1,
                    "date_released": 1, "payments_made": 1,
                    "outstanding_balance": 1,
                },
            )
        )

        for loan in current_loans:
            expected_next = loan["date_released"] + relativedelta(
                months=loan["payments_made"] + 1
            )
            days_late = (now - expected_next).days

            if days_late > 30:
                self.db.loans.update_one(
                    {"loan_id": loan["loan_id"]},
                    {"$set": {"status": "Past Due", "updated_at": now}},
                )
                marked += 1
                details.append({
                    "loan_id": loan["loan_id"],
                    "member_id": loan["member_id"],
                    "member_name": loan["member_name"],
                    "reason": "missed_payment",
                    "days_late": days_late,
                    "outstanding_balance": loan["outstanding_balance"],
                })
                log_audit(
                    action="AUTO_MARK_PAST_DUE",
                    resource="loans",
                    resource_id=loan["loan_id"],
                    details={
                        "reason": "missed_payment",
                        "days_late": days_late,
                        "expected_payment_date": expected_next.isoformat(),
                    },
                )

        return {
            "run_at": now.isoformat(),
            "marked_past_due": marked,
            "details": details,
        }