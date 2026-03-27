# backend/tests/test_past_due.py
"""
Tests for the past-due automation feature.

We test the service method directly (unit) and the manual trigger
endpoint (integration). The scheduler itself is disabled in testing
(SCHEDULER_ENABLED=false in TestingConfig).
"""
import pytest
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from tests.conftest import auth_header
from tests.fixtures.member_fixtures import valid_member_payload


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _make_current_loan(db, member_id: str, member_name: str,
                        released_days_ago: int = 60,
                        term_months: int = 12,
                        payments_made: int = 0,
                        loan_id_suffix: str = "01") -> str:
    """
    Directly inserts a Current loan into the test DB.
    Returns the loan_id.
    """
    from app.utils import utcnow
    now = utcnow()
    released = now - timedelta(days=released_days_ago)
    maturity = released + relativedelta(months=term_months)

    loan_id = f"LN-TEST-PD-{loan_id_suffix}"
    db.loans.insert_one({
        "loan_id": loan_id,
        "member_id": member_id,
        "member_name": member_name,
        "loan_type": "Multi-Purpose",
        "principal": 10000.0,
        "interest_rate": 12.0,
        "term_months": term_months,
        "monthly_amortization": 888.49,
        "total_payable": 10661.88,
        "total_interest": 661.88,
        "outstanding_balance": 10000.0 - (payments_made * 800),
        "total_paid": payments_made * 888.49,
        "payments_made": payments_made,
        "status": "Current",
        "purpose": "Test loan for past-due automation",
        "co_makers": [],
        "collateral": None,
        "date_applied": released - timedelta(days=7),
        "date_approved": released - timedelta(days=3),
        "date_released": released,
        "maturity_date": maturity,
        "approved_by": "test",
        "approved_at": released - timedelta(days=3),
        "rejected_reason": None,
        "submitted_by": "test",
        "created_at": released,
        "updated_at": released,
    })
    return loan_id


# ------------------------------------------------------------------ #
# Module-scoped member
# ------------------------------------------------------------------ #

@pytest.fixture(scope="module")
def pd_member(client, admin_token, app, db):
    resp = client.post(
        "/api/v1/members",
        json=valid_member_payload(
            {"phone": "09170000044", "email": "pastduetest@email.com"}
        ),
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 201
    member = resp.get_json()
    yield member

    with app.app_context():
        mid = member["member_id"]
        db.members.delete_one({"member_id": mid})
        db.savings_accounts.delete_many({"member_id": mid})
        db.share_capital.delete_many({"member_id": mid})
        db.loans.delete_many({"member_id": mid})
        db.audit_logs.delete_many({"resource": "loans",
                                    "action": "AUTO_MARK_PAST_DUE"})


# ------------------------------------------------------------------ #
# Unit tests — LoanService.mark_past_due()
# ------------------------------------------------------------------ #

class TestMarkPastDueService:

    def test_maturity_passed_marked_past_due(self, app, db, pd_member):
        """A loan whose maturity_date is in the past must be flipped to Past Due."""
        loan_id = _make_current_loan(
            db,
            member_id=pd_member["member_id"],
            member_name="Test Member",
            released_days_ago=400,  # released 400 days ago
            term_months=12,         # 12-month loan → matured ~35 days ago
            loan_id_suffix="M1",
        )
        with app.app_context():
            from app.services.loan_service import LoanService
            result = LoanService().mark_past_due()

        assert result["marked_past_due"] >= 1
        affected = [d for d in result["details"] if d["loan_id"] == loan_id]
        assert affected
        assert affected[0]["reason"] == "maturity_date_passed"
        assert affected[0]["days_overdue"] > 0

        with app.app_context():
            loan = db.loans.find_one({"loan_id": loan_id})
            assert loan["status"] == "Past Due"

        db.loans.delete_one({"loan_id": loan_id})

    def test_missed_payment_over_30_days_marked_past_due(self, app, db, pd_member):
        """
        A Current loan where the next expected payment is > 30 days overdue
        must be marked Past Due even if maturity hasn't been reached.
        """
        # Released 65 days ago, 0 payments made.
        # Expected first payment was 30 days after release = 35 days ago.
        # 35 > 30 → should be marked Past Due.
        loan_id = _make_current_loan(
            db,
            member_id=pd_member["member_id"],
            member_name="Test Member",
            released_days_ago=65,
            term_months=24,   # long term so maturity hasn't passed
            payments_made=0,
            loan_id_suffix="M2",
        )
        with app.app_context():
            from app.services.loan_service import LoanService
            result = LoanService().mark_past_due()

        affected = [d for d in result["details"] if d["loan_id"] == loan_id]
        assert affected
        assert affected[0]["reason"] == "missed_payment"

        with app.app_context():
            loan = db.loans.find_one({"loan_id": loan_id})
            assert loan["status"] == "Past Due"

        db.loans.delete_one({"loan_id": loan_id})

    def test_on_time_loan_not_affected(self, app, db, pd_member):
        """A loan with payments up to date must remain Current."""
        # Released 35 days ago, 1 payment made.
        # Next payment due in ~25 days — not overdue.
        loan_id = _make_current_loan(
            db,
            member_id=pd_member["member_id"],
            member_name="Test Member",
            released_days_ago=35,
            term_months=24,
            payments_made=1,
            loan_id_suffix="M3",
        )
        with app.app_context():
            from app.services.loan_service import LoanService
            LoanService().mark_past_due()
            loan = db.loans.find_one({"loan_id": loan_id})
            assert loan["status"] == "Current"

        db.loans.delete_one({"loan_id": loan_id})

    def test_already_past_due_not_double_counted(self, app, db, pd_member):
        """A loan already marked Past Due must not appear in the results again."""
        from app.utils import utcnow
        now = utcnow()
        loan_id = f"LN-TEST-PD-M4"
        db.loans.insert_one({
            "loan_id": loan_id,
            "member_id": pd_member["member_id"],
            "member_name": "Test Member",
            "loan_type": "Multi-Purpose",
            "principal": 5000.0,
            "interest_rate": 12.0,
            "term_months": 6,
            "monthly_amortization": 855.0,
            "total_payable": 5130.0,
            "total_interest": 130.0,
            "outstanding_balance": 5000.0,
            "total_paid": 0.0,
            "payments_made": 0,
            "status": "Past Due",      # already Past Due
            "purpose": "Test",
            "co_makers": [],
            "collateral": None,
            "date_released": now - timedelta(days=300),
            "maturity_date": now - timedelta(days=100),
            "approved_by": "test",
            "approved_at": now - timedelta(days=305),
            "rejected_reason": None,
            "submitted_by": "test",
            "created_at": now - timedelta(days=310),
            "updated_at": now - timedelta(days=100),
        })

        with app.app_context():
            from app.services.loan_service import LoanService
            result = LoanService().mark_past_due()

        affected = [d for d in result["details"] if d["loan_id"] == loan_id]
        assert not affected  # must not be in results

        db.loans.delete_one({"loan_id": loan_id})

    def test_closed_loan_not_affected(self, app, db, pd_member):
        """A Closed loan must never be touched."""
        from app.utils import utcnow
        now = utcnow()
        loan_id = "LN-TEST-PD-M5"
        db.loans.insert_one({
            "loan_id": loan_id,
            "member_id": pd_member["member_id"],
            "member_name": "Test Member",
            "loan_type": "Multi-Purpose",
            "principal": 5000.0,
            "interest_rate": 12.0,
            "term_months": 6,
            "monthly_amortization": 855.0,
            "total_payable": 5130.0,
            "total_interest": 130.0,
            "outstanding_balance": 0.0,
            "total_paid": 5130.0,
            "payments_made": 6,
            "status": "Closed",
            "purpose": "Test",
            "co_makers": [],
            "collateral": None,
            "date_released": now - timedelta(days=200),
            "maturity_date": now - timedelta(days=10),
            "approved_by": "test",
            "approved_at": now - timedelta(days=205),
            "rejected_reason": None,
            "submitted_by": "test",
            "created_at": now - timedelta(days=210),
            "updated_at": now - timedelta(days=10),
        })

        with app.app_context():
            from app.services.loan_service import LoanService
            LoanService().mark_past_due()
            loan = db.loans.find_one({"loan_id": loan_id})
            assert loan["status"] == "Closed"

        db.loans.delete_one({"loan_id": loan_id})

    def test_mark_past_due_returns_correct_structure(self, app):
        with app.app_context():
            from app.services.loan_service import LoanService
            result = LoanService().mark_past_due()

        assert "run_at" in result
        assert "marked_past_due" in result
        assert "details" in result
        assert isinstance(result["marked_past_due"], int)
        assert isinstance(result["details"], list)

    def test_mark_past_due_idempotent(self, app, db, pd_member):
        """Running the job twice should not double-count."""
        loan_id = _make_current_loan(
            db,
            member_id=pd_member["member_id"],
            member_name="Test Member",
            released_days_ago=400,
            term_months=12,
            loan_id_suffix="M6",
        )
        with app.app_context():
            from app.services.loan_service import LoanService
            svc = LoanService()
            first = svc.mark_past_due()
            second = svc.mark_past_due()

        first_count = len([d for d in first["details"] if d["loan_id"] == loan_id])
        second_count = len([d for d in second["details"] if d["loan_id"] == loan_id])

        assert first_count == 1
        assert second_count == 0   # already Past Due on second run

        db.loans.delete_one({"loan_id": loan_id})


# ------------------------------------------------------------------ #
# Integration tests — POST /admin/past-due-check endpoint
# ------------------------------------------------------------------ #

class TestPastDueEndpoint:

    def test_endpoint_success(self, client, admin_token):
        resp = client.post(
            "/api/v1/admin/past-due-check",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert "marked_past_due" in body
        assert "run_at" in body
        assert "details" in body

    def test_endpoint_accessible_to_manager(self, client, manager_token):
        resp = client.post(
            "/api/v1/admin/past-due-check",
            headers=auth_header(manager_token),
        )
        assert resp.status_code == 200

    def test_endpoint_forbidden_for_cashier(self, client, cashier_token):
        resp = client.post(
            "/api/v1/admin/past-due-check",
            headers=auth_header(cashier_token),
        )
        assert resp.status_code == 403

    def test_endpoint_requires_auth(self, client):
        assert client.post("/api/v1/admin/past-due-check").status_code == 401

    def test_dormancy_check_endpoint(self, client, admin_token):
        resp = client.post(
            "/api/v1/admin/dormancy-check",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert "accounts_marked_dormant" in resp.get_json()

    def test_scheduler_status_endpoint(self, client, admin_token):
        resp = client.get(
            "/api/v1/admin/scheduler/status",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert "running" in body
        assert "jobs" in body
        # Scheduler is disabled in testing — running should be False
        assert body["running"] is False

    def test_scheduler_status_forbidden_for_manager(self, client, manager_token):
        resp = client.get(
            "/api/v1/admin/scheduler/status",
            headers=auth_header(manager_token),
        )
        assert resp.status_code == 403