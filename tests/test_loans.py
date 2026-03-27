# backend/tests/test_loans.py
import pytest
from tests.conftest import auth_header
from tests.fixtures.member_fixtures import valid_member_payload
from tests.fixtures.loan_fixtures import valid_loan_payload, payment_payload


# ------------------------------------------------------------------ #
# Session-scoped member shared by all loan tests
# ------------------------------------------------------------------ #

@pytest.fixture(scope="module")
def test_member(client, admin_token, app, db):
    """Creates one member for the entire loan test module."""
    resp = client.post(
        "/api/v1/members",
        json=valid_member_payload({"phone": "09170000099", "email": "loantest@email.com"}),
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
        db.loan_payments.delete_many({"member_id": mid})


def _apply(client, token, member_id, overrides=None) -> dict:
    resp = client.post(
        "/api/v1/loans",
        json=valid_loan_payload(member_id, overrides),
        headers=auth_header(token),
    )
    return resp


def _cleanup_loan(app, db, loan_id: str):
    with app.app_context():
        db.loans.delete_one({"loan_id": loan_id})
        db.loan_payments.delete_many({"loan_id": loan_id})


# ------------------------------------------------------------------ #
# Calculator
# ------------------------------------------------------------------ #

class TestCalculator:

    def test_calculator_returns_correct_fields(self, client, admin_token):
        resp = client.get(
            "/api/v1/loans/calculator?loan_type=Multi-Purpose&principal=50000&term_months=24",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        for key in ("monthly_amortization", "total_payable", "total_interest", "schedule"):
            assert key in body
        assert len(body["schedule"]) == 24

    def test_calculator_known_value(self, client, admin_token):
        """₱50,000 @ 12% p.a. for 24 months = ~₱2,354.17/month."""
        resp = client.get(
            "/api/v1/loans/calculator?loan_type=Multi-Purpose&principal=50000&term_months=24",
            headers=auth_header(admin_token),
        )
        body = resp.get_json()
        assert abs(body["monthly_amortization"] - 2354.17) < 0.50

    def test_calculator_invalid_loan_type(self, client, admin_token):
        resp = client.get(
            "/api/v1/loans/calculator?loan_type=BadType&principal=10000&term_months=6",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_calculator_term_exceeds_max(self, client, admin_token):
        resp = client.get(
            "/api/v1/loans/calculator?loan_type=Emergency&principal=10000&term_months=24",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_calculator_below_minimum_principal(self, client, admin_token):
        resp = client.get(
            "/api/v1/loans/calculator?loan_type=Multi-Purpose&principal=500&term_months=6",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_calculator_requires_auth(self, client):
        resp = client.get(
            "/api/v1/loans/calculator?loan_type=Multi-Purpose&principal=10000&term_months=6"
        )
        assert resp.status_code == 401


# ------------------------------------------------------------------ #
# List loans
# ------------------------------------------------------------------ #

class TestListLoans:

    def test_list_requires_auth(self, client):
        resp = client.get("/api/v1/loans")
        assert resp.status_code == 401

    def test_list_returns_envelope(self, client, admin_token):
        resp = client.get("/api/v1/loans", headers=auth_header(admin_token))
        assert resp.status_code == 200
        body = resp.get_json()
        assert "data" in body
        assert "pagination" in body

    def test_list_filter_by_member(self, client, admin_token, test_member):
        resp = client.get(
            f"/api/v1/loans?member_id={test_member['member_id']}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    def test_list_filter_by_status(self, client, admin_token):
        resp = client.get(
            "/api/v1/loans?status=Pending", headers=auth_header(admin_token)
        )
        body = resp.get_json()
        assert resp.status_code == 200
        for loan in body["data"]:
            assert loan["status"] == "Pending"


# ------------------------------------------------------------------ #
# Apply (POST /loans)
# ------------------------------------------------------------------ #

class TestApplyLoan:

    def test_apply_success(self, client, admin_token, test_member, app, db):
        resp = _apply(client, admin_token, test_member["member_id"])
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["loan_id"].startswith("LN-")
        assert body["status"] == "Pending"
        assert body["member_id"] == test_member["member_id"]
        assert "monthly_amortization" in body
        assert "outstanding_balance" in body
        _cleanup_loan(app, db, body["loan_id"])

    def test_apply_sets_correct_rate_for_type(self, client, admin_token, test_member, app, db):
        resp = _apply(client, admin_token, test_member["member_id"],
                      {"loan_type": "Emergency", "principal": 5000, "term_months": 6})
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["interest_rate"] == 10.0   # Emergency rate
        _cleanup_loan(app, db, body["loan_id"])

    def test_apply_requires_write_role(self, client, cashier_token, test_member):
        resp = _apply(client, cashier_token, test_member["member_id"])
        assert resp.status_code == 403

    def test_apply_unknown_member(self, client, admin_token):
        resp = _apply(client, admin_token, "M-0000-9999")
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_apply_inactive_member(self, client, admin_token, app, db):
        # Create a member then suspend them
        m_resp = client.post(
            "/api/v1/members",
            json=valid_member_payload({"phone": "09170000098", "email": "suspended@email.com"}),
            headers=auth_header(admin_token),
        )
        m = m_resp.get_json()
        client.put(
            f"/api/v1/members/{m['member_id']}",
            json={"status": "Suspended"},
            headers=auth_header(admin_token),
        )
        resp = _apply(client, admin_token, m["member_id"])
        assert resp.status_code == 400
        assert "not Active" in resp.get_json()["error"]

        with app.app_context():
            db.members.delete_one({"member_id": m["member_id"]})
            db.savings_accounts.delete_many({"member_id": m["member_id"]})
            db.share_capital.delete_many({"member_id": m["member_id"]})

    def test_apply_above_30k_requires_comaker(self, client, admin_token, test_member):
        resp = _apply(client, admin_token, test_member["member_id"],
                      {"principal": 50000, "co_makers": []})
        assert resp.status_code == 400
        assert "co-maker" in resp.get_json()["error"].lower()

    def test_apply_above_30k_with_comaker_succeeds(self, client, admin_token, test_member, app, db):
        resp = _apply(client, admin_token, test_member["member_id"], {
            "principal": 50000,
            "co_makers": [{"member_id": "M-2024-0999", "name": "Ana Reyes"}],
        })
        assert resp.status_code == 201
        _cleanup_loan(app, db, resp.get_json()["loan_id"])

    def test_apply_term_exceeds_max_for_type(self, client, admin_token, test_member):
        resp = _apply(client, admin_token, test_member["member_id"],
                      {"loan_type": "Salary", "term_months": 12})
        assert resp.status_code == 400
        assert "Maximum term" in resp.get_json()["error"]

    def test_apply_missing_required_fields(self, client, admin_token, test_member):
        resp = client.post(
            "/api/v1/loans",
            json={"member_id": test_member["member_id"]},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_apply_invalid_loan_type(self, client, admin_token, test_member):
        resp = _apply(client, admin_token, test_member["member_id"],
                      {"loan_type": "VIP Loan"})
        assert resp.status_code == 400

    def test_apply_below_minimum_principal(self, client, admin_token, test_member):
        resp = _apply(client, admin_token, test_member["member_id"],
                      {"principal": 500})
        assert resp.status_code == 400

    def test_apply_max_two_active_loans(self, client, admin_token, test_member, app, db):
        """Enforce MAX_ACTIVE_LOANS = 2."""
        # Apply and approve+release two loans
        ids = []
        for i in range(2):
            r = _apply(client, admin_token, test_member["member_id"],
                       {"principal": 5000, "term_months": 6})
            assert r.status_code == 201
            loan_id = r.get_json()["loan_id"]
            ids.append(loan_id)
            client.put(f"/api/v1/loans/{loan_id}/approve",
                       json={}, headers=auth_header(admin_token))
            client.put(f"/api/v1/loans/{loan_id}/release",
                       json={"or_number": f"OR-{i}"}, headers=auth_header(admin_token))

        # Third application must be rejected by the business rule
        resp = _apply(client, admin_token, test_member["member_id"],
                      {"principal": 5000, "term_months": 6})
        assert resp.status_code == 400
        assert "active loan" in resp.get_json()["error"].lower()

        for lid in ids:
            _cleanup_loan(app, db, lid)


# ------------------------------------------------------------------ #
# Get loan detail
# ------------------------------------------------------------------ #

class TestGetLoan:

    @pytest.fixture(autouse=True)
    def setup_loan(self, client, admin_token, test_member, app, db):
        resp = _apply(client, admin_token, test_member["member_id"])
        self.loan = resp.get_json()
        yield
        _cleanup_loan(app, db, self.loan["loan_id"])

    def test_get_loan_success(self, client, admin_token):
        resp = client.get(
            f"/api/v1/loans/{self.loan['loan_id']}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.get_json()["loan_id"] == self.loan["loan_id"]

    def test_get_loan_not_found(self, client, admin_token):
        resp = client.get("/api/v1/loans/LN-0000-9999", headers=auth_header(admin_token))
        assert resp.status_code == 404

    def test_get_loan_accessible_to_cashier(self, client, cashier_token):
        resp = client.get(
            f"/api/v1/loans/{self.loan['loan_id']}",
            headers=auth_header(cashier_token),
        )
        assert resp.status_code == 200


# ------------------------------------------------------------------ #
# Amortization schedule
# ------------------------------------------------------------------ #

class TestSchedule:

    @pytest.fixture(autouse=True)
    def setup_loan(self, client, admin_token, test_member, app, db):
        resp = _apply(client, admin_token, test_member["member_id"],
                      {"principal": 20000, "term_months": 12})
        self.loan = resp.get_json()
        yield
        _cleanup_loan(app, db, self.loan["loan_id"])

    def test_schedule_length_matches_term(self, client, admin_token):
        resp = client.get(
            f"/api/v1/loans/{self.loan['loan_id']}/schedule",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body["schedule"]) == 12

    def test_schedule_last_balance_is_zero(self, client, admin_token):
        resp = client.get(
            f"/api/v1/loans/{self.loan['loan_id']}/schedule",
            headers=auth_header(admin_token),
        )
        schedule = resp.get_json()["schedule"]
        assert schedule[-1]["balance"] == 0.0

    def test_schedule_not_found(self, client, admin_token):
        resp = client.get(
            "/api/v1/loans/LN-0000-9999/schedule",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404


# ------------------------------------------------------------------ #
# Approve
# ------------------------------------------------------------------ #

class TestApproveLoan:

    @pytest.fixture(autouse=True)
    def setup_loan(self, client, admin_token, test_member, app, db):
        resp = _apply(client, admin_token, test_member["member_id"])
        self.loan = resp.get_json()
        yield
        _cleanup_loan(app, db, self.loan["loan_id"])

    def test_approve_success(self, client, admin_token):
        resp = client.put(
            f"/api/v1/loans/{self.loan['loan_id']}/approve",
            json={},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "Approved"

    def test_approve_requires_manager_or_admin(self, client, cashier_token):
        resp = client.put(
            f"/api/v1/loans/{self.loan['loan_id']}/approve",
            json={},
            headers=auth_header(cashier_token),
        )
        assert resp.status_code == 403

    def test_cannot_approve_non_pending(self, client, admin_token):
        # Approve once
        client.put(f"/api/v1/loans/{self.loan['loan_id']}/approve",
                   json={}, headers=auth_header(admin_token))
        # Try to approve again
        resp = client.put(
            f"/api/v1/loans/{self.loan['loan_id']}/approve",
            json={},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400
        assert "Pending" in resp.get_json()["error"]


# ------------------------------------------------------------------ #
# Reject
# ------------------------------------------------------------------ #

class TestRejectLoan:

    @pytest.fixture(autouse=True)
    def setup_loan(self, client, admin_token, test_member, app, db):
        resp = _apply(client, admin_token, test_member["member_id"])
        self.loan = resp.get_json()
        yield
        _cleanup_loan(app, db, self.loan["loan_id"])

    def test_reject_success(self, client, admin_token):
        resp = client.put(
            f"/api/v1/loans/{self.loan['loan_id']}/reject",
            json={"reason": "Insufficient income documentation"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "Rejected"
        assert body["rejected_reason"] == "Insufficient income documentation"

    def test_reject_missing_reason(self, client, admin_token):
        resp = client.put(
            f"/api/v1/loans/{self.loan['loan_id']}/reject",
            json={},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_reject_requires_manager(self, client, cashier_token):
        resp = client.put(
            f"/api/v1/loans/{self.loan['loan_id']}/reject",
            json={"reason": "Hacking attempt"},
            headers=auth_header(cashier_token),
        )
        assert resp.status_code == 403


# ------------------------------------------------------------------ #
# Release
# ------------------------------------------------------------------ #

class TestReleaseLoan:

    @pytest.fixture(autouse=True)
    def setup_approved_loan(self, client, admin_token, test_member, app, db):
        r = _apply(client, admin_token, test_member["member_id"])
        self.loan = r.get_json()
        client.put(f"/api/v1/loans/{self.loan['loan_id']}/approve",
                   json={}, headers=auth_header(admin_token))
        yield
        _cleanup_loan(app, db, self.loan["loan_id"])

    def test_release_success(self, client, admin_token):
        resp = client.put(
            f"/api/v1/loans/{self.loan['loan_id']}/release",
            json={"or_number": "OR-RELEASE-001"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "Current"
        assert body["date_released"] is not None
        assert body["maturity_date"] is not None

    def test_release_requires_cashier_or_above(self, client, manager_token):
        resp = client.put(
            f"/api/v1/loans/{self.loan['loan_id']}/release",
            json={"or_number": "OR-001"},
            headers=auth_header(manager_token),
        )
        assert resp.status_code == 200  # manager is allowed

    def test_release_missing_or_number(self, client, admin_token):
        resp = client.put(
            f"/api/v1/loans/{self.loan['loan_id']}/release",
            json={},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_cannot_release_pending_loan(self, client, admin_token, test_member, app, db):
        r = _apply(client, admin_token, test_member["member_id"])
        pending_loan = r.get_json()
        resp = client.put(
            f"/api/v1/loans/{pending_loan['loan_id']}/release",
            json={"or_number": "OR-DIRECT"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400
        assert "Approved" in resp.get_json()["error"]
        _cleanup_loan(app, db, pending_loan["loan_id"])


# ------------------------------------------------------------------ #
# Post payment
# ------------------------------------------------------------------ #

class TestPostPayment:

    @pytest.fixture(autouse=True)
    def setup_current_loan(self, client, admin_token, test_member, app, db):
        r = _apply(client, admin_token, test_member["member_id"],
                   {"principal": 12000, "term_months": 12})
        self.loan = r.get_json()
        client.put(f"/api/v1/loans/{self.loan['loan_id']}/approve",
                   json={}, headers=auth_header(admin_token))
        client.put(f"/api/v1/loans/{self.loan['loan_id']}/release",
                   json={"or_number": "OR-REL-001"}, headers=auth_header(admin_token))
        yield
        _cleanup_loan(app, db, self.loan["loan_id"])

    def test_post_payment_success(self, client, admin_token):
        resp = client.post(
            f"/api/v1/loans/{self.loan['loan_id']}/payments",
            json=payment_payload(),
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert "payment_id" in body
        assert "balance_after" in body
        assert body["balance_after"] < 12000

    def test_payment_reduces_outstanding_balance(self, client, admin_token):
        client.post(
            f"/api/v1/loans/{self.loan['loan_id']}/payments",
            json=payment_payload({"or_number": "OR-PMT-001"}),
            headers=auth_header(admin_token),
        )
        loan = client.get(
            f"/api/v1/loans/{self.loan['loan_id']}",
            headers=auth_header(admin_token),
        ).get_json()
        assert loan["outstanding_balance"] < 12000
        assert loan["payments_made"] == 1

    def test_payment_allocation_fields(self, client, admin_token):
        resp = client.post(
            f"/api/v1/loans/{self.loan['loan_id']}/payments",
            json=payment_payload({"or_number": "OR-ALLOC-001"}),
            headers=auth_header(admin_token),
        )
        body = resp.get_json()
        for field in ("principal_portion", "interest_portion", "penalty_portion", "excess"):
            assert field in body

    def test_payment_history_recorded(self, client, admin_token):
        client.post(
            f"/api/v1/loans/{self.loan['loan_id']}/payments",
            json=payment_payload({"or_number": "OR-HIST-001"}),
            headers=auth_header(admin_token),
        )
        resp = client.get(
            f"/api/v1/loans/{self.loan['loan_id']}/payments",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert len(resp.get_json()["payments"]) >= 1

    def test_payment_requires_cashier_or_above(self, client, manager_token):
        resp = client.post(
            f"/api/v1/loans/{self.loan['loan_id']}/payments",
            json=payment_payload({"or_number": "OR-ROLE-001"}),
            headers=auth_header(manager_token),
        )
        assert resp.status_code == 201

    def test_payment_loan_officer_blocked(self, client, app, db):
        # loan_officer cannot post payments
        from app.services.user_service import UserService
        with app.app_context():
            UserService().create_user({
                "full_name": "Test Officer",
                "email": "testofficer_loan@coopcore.ph",
                "password": "Officer@1234",
                "role": "loan_officer",
            }, created_by="test")
        lo_resp = client.post("/api/v1/auth/login",
                              json={"email": "testofficer_loan@coopcore.ph",
                                    "password": "Officer@1234"})
        lo_token = lo_resp.get_json()["access_token"]

        resp = client.post(
            f"/api/v1/loans/{self.loan['loan_id']}/payments",
            json=payment_payload({"or_number": "OR-LO-001"}),
            headers=auth_header(lo_token),
        )
        assert resp.status_code == 403

        with app.app_context():
            db.users.delete_one({"email": "testofficer_loan@coopcore.ph"})

    def test_payment_cannot_post_on_pending_loan(self, client, admin_token, test_member, app, db):
        r = _apply(client, admin_token, test_member["member_id"])
        pending = r.get_json()
        resp = client.post(
            f"/api/v1/loans/{pending['loan_id']}/payments",
            json=payment_payload(),
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400
        _cleanup_loan(app, db, pending["loan_id"])

    def test_payment_missing_or_number(self, client, admin_token):
        p = payment_payload()
        p.pop("or_number")
        resp = client.post(
            f"/api/v1/loans/{self.loan['loan_id']}/payments",
            json=p,
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_full_repayment_closes_loan(self, client, admin_token):
        """Pay enough to zero the balance — loan must become Closed."""
        # Get the current outstanding
        loan = client.get(
            f"/api/v1/loans/{self.loan['loan_id']}",
            headers=auth_header(admin_token),
        ).get_json()
        outstanding = loan["outstanding_balance"]

        client.post(
            f"/api/v1/loans/{self.loan['loan_id']}/payments",
            json=payment_payload({"amount_paid": outstanding + 5000,
                                  "or_number": "OR-FULL-001"}),
            headers=auth_header(admin_token),
        )
        closed = client.get(
            f"/api/v1/loans/{self.loan['loan_id']}",
            headers=auth_header(admin_token),
        ).get_json()
        assert closed["status"] == "Closed"
        assert closed["outstanding_balance"] == 0.0