# backend/tests/test_admin.py
import pytest
from tests.conftest import auth_header
from tests.fixtures.member_fixtures import valid_member_payload


# ------------------------------------------------------------------ #
# Dashboard
# ------------------------------------------------------------------ #

class TestDashboard:

    def test_dashboard_success(self, client, admin_token):
        resp = client.get("/api/v1/admin/dashboard", headers=auth_header(admin_token))
        assert resp.status_code == 200
        body = resp.get_json()
        assert "members" in body
        assert "loans" in body
        assert "savings" in body
        assert "share_capital" in body
        assert "as_of" in body

    def test_dashboard_member_keys(self, client, admin_token):
        body = client.get(
            "/api/v1/admin/dashboard", headers=auth_header(admin_token)
        ).get_json()
        assert "total" in body["members"]
        assert "active" in body["members"]

    def test_dashboard_loan_keys(self, client, admin_token):
        body = client.get(
            "/api/v1/admin/dashboard", headers=auth_header(admin_token)
        ).get_json()
        for key in ("total", "active", "past_due", "pending_approval", "total_outstanding"):
            assert key in body["loans"]

    def test_dashboard_accessible_to_manager(self, client, manager_token):
        assert client.get(
            "/api/v1/admin/dashboard", headers=auth_header(manager_token)
        ).status_code == 200

    def test_dashboard_forbidden_for_cashier(self, client, cashier_token):
        assert client.get(
            "/api/v1/admin/dashboard", headers=auth_header(cashier_token)
        ).status_code == 403

    def test_dashboard_requires_auth(self, client):
        assert client.get("/api/v1/admin/dashboard").status_code == 401


# ------------------------------------------------------------------ #
# Settings
# ------------------------------------------------------------------ #

class TestSettings:

    def test_get_settings_success(self, client, admin_token):
        resp = client.get("/api/v1/admin/settings", headers=auth_header(admin_token))
        assert resp.status_code == 200
        body = resp.get_json()
        assert "coop_name" in body
        assert "default_loan_rate" in body
        assert "share_par_value" in body

    def test_get_settings_bootstraps_defaults(self, client, admin_token):
        body = client.get(
            "/api/v1/admin/settings", headers=auth_header(admin_token)
        ).get_json()
        assert body["default_loan_rate"] == 12.0
        assert body["share_par_value"] == 100.0
        assert body["withholding_tax_rate"] == 20.0

    def test_update_settings_success(self, client, admin_token, app, db):
        resp = client.put(
            "/api/v1/admin/settings",
            json={"coop_name": "Test Cooperative Updated", "default_savings_rate": 4.0},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["coop_name"] == "Test Cooperative Updated"
        assert body["default_savings_rate"] == 4.0

        # Restore
        client.put(
            "/api/v1/admin/settings",
            json={"coop_name": "CoopCore Multi-Purpose Cooperative",
                  "default_savings_rate": 3.0},
            headers=auth_header(admin_token),
        )

    def test_update_settings_unknown_fields_ignored(self, client, admin_token):
        resp = client.put(
            "/api/v1/admin/settings",
            json={"unknown_field": "hacked", "coop_name": "Valid Name"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert "unknown_field" not in resp.get_json()

    def test_update_settings_invalid_rate_type(self, client, admin_token):
        resp = client.put(
            "/api/v1/admin/settings",
            json={"default_loan_rate": "not-a-number"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_update_settings_empty_body(self, client, admin_token):
        resp = client.put(
            "/api/v1/admin/settings",
            json={},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_settings_requires_super_admin(self, client, manager_token):
        assert client.get(
            "/api/v1/admin/settings", headers=auth_header(manager_token)
        ).status_code == 403

    def test_settings_update_requires_super_admin(self, client, manager_token):
        assert client.put(
            "/api/v1/admin/settings",
            json={"coop_name": "Hacked"},
            headers=auth_header(manager_token),
        ).status_code == 403

    def test_settings_requires_auth(self, client):
        assert client.get("/api/v1/admin/settings").status_code == 401


# ------------------------------------------------------------------ #
# Audit logs
# ------------------------------------------------------------------ #

class TestAuditLogs:

    def test_audit_logs_success(self, client, admin_token):
        resp = client.get("/api/v1/admin/audit-logs", headers=auth_header(admin_token))
        assert resp.status_code == 200
        body = resp.get_json()
        assert "data" in body
        assert "pagination" in body

    def test_audit_logs_have_required_fields(self, client, admin_token):
        body = client.get(
            "/api/v1/admin/audit-logs", headers=auth_header(admin_token)
        ).get_json()
        if body["data"]:
            entry = body["data"][0]
            for field in ("action", "resource", "resource_id", "created_at"):
                assert field in entry

    def test_audit_logs_filter_by_resource(self, client, admin_token):
        resp = client.get(
            "/api/v1/admin/audit-logs?resource=members",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        for entry in resp.get_json()["data"]:
            assert entry["resource"] == "members"

    def test_audit_logs_filter_by_action(self, client, admin_token):
        resp = client.get(
            "/api/v1/admin/audit-logs?action=LOGIN",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        for entry in resp.get_json()["data"]:
            assert "LOGIN" in entry["action"].upper()

    def test_audit_logs_pagination(self, client, admin_token):
        resp = client.get(
            "/api/v1/admin/audit-logs?page=1&per_page=5",
            headers=auth_header(admin_token),
        )
        body = resp.get_json()
        assert body["pagination"]["per_page"] == 5
        assert len(body["data"]) <= 5

    def test_audit_logs_per_page_capped(self, client, admin_token):
        resp = client.get(
            "/api/v1/admin/audit-logs?per_page=9999",
            headers=auth_header(admin_token),
        )
        assert resp.get_json()["pagination"]["per_page"] <= 200

    def test_audit_logs_sorted_newest_first(self, client, admin_token):
        body = client.get(
            "/api/v1/admin/audit-logs", headers=auth_header(admin_token)
        ).get_json()
        dates = [e["created_at"] for e in body["data"]]
        assert dates == sorted(dates, reverse=True)

    def test_audit_logs_requires_super_admin(self, client, manager_token):
        assert client.get(
            "/api/v1/admin/audit-logs", headers=auth_header(manager_token)
        ).status_code == 403

    def test_audit_logs_requires_auth(self, client):
        assert client.get("/api/v1/admin/audit-logs").status_code == 401


# ------------------------------------------------------------------ #
# Reports
# ------------------------------------------------------------------ #

class TestReports:

    @pytest.fixture(scope="class")
    def seeded_member(self, client, admin_token, app, db):
        resp = client.post(
            "/api/v1/members",
            json=valid_member_payload(
                {"phone": "09170000011", "email": "adminreport@email.com"}
            ),
            headers=auth_header(admin_token),
        )
        member = resp.get_json()
        yield member
        with app.app_context():
            mid = member["member_id"]
            db.members.delete_one({"member_id": mid})
            db.savings_accounts.delete_many({"member_id": mid})
            db.share_capital.delete_many({"member_id": mid})

    # ---- Members report ----

    def test_member_report_structure(self, client, admin_token, seeded_member):
        resp = client.get(
            "/api/v1/admin/reports/members",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert "total" in body
        assert "status_counts" in body
        assert "members" in body
        assert isinstance(body["members"], list)

    def test_member_report_filter_by_status(self, client, admin_token):
        resp = client.get(
            "/api/v1/admin/reports/members?status=Active",
            headers=auth_header(admin_token),
        )
        body = resp.get_json()
        assert resp.status_code == 200
        for m in body["members"]:
            assert m["status"] == "Active"

    def test_member_report_filter_by_type(self, client, admin_token):
        resp = client.get(
            "/api/v1/admin/reports/members?membership_type=Regular",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        for m in resp.get_json()["members"]:
            assert m["membership_type"] == "Regular"

    def test_member_report_accessible_to_manager(self, client, manager_token):
        assert client.get(
            "/api/v1/admin/reports/members", headers=auth_header(manager_token)
        ).status_code == 200

    def test_member_report_forbidden_for_cashier(self, client, cashier_token):
        assert client.get(
            "/api/v1/admin/reports/members", headers=auth_header(cashier_token)
        ).status_code == 403

    # ---- Loans report ----

    def test_loan_report_structure(self, client, admin_token):
        resp = client.get(
            "/api/v1/admin/reports/loans",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert "total_loans" in body
        assert "total_portfolio_outstanding" in body
        assert "summary_by_status" in body
        assert "loans" in body

    def test_loan_report_filter_by_status(self, client, admin_token):
        resp = client.get(
            "/api/v1/admin/reports/loans?status=Pending",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        for loan in resp.get_json()["loans"]:
            assert loan["status"] == "Pending"

    def test_loan_report_past_due_has_days_overdue(self, client, admin_token, app, db):
        # Manually insert a Past Due loan to test days_overdue field
        from datetime import timedelta
        past_date = __import__("datetime").datetime.utcnow() - timedelta(days=10)
        with app.app_context():
            db.loans.insert_one({
                "loan_id": "LN-TEST-PASTDUE",
                "member_id": "M-TEST-001",
                "member_name": "Test Member",
                "loan_type": "Multi-Purpose",
                "principal": 10000,
                "outstanding_balance": 8000,
                "monthly_amortization": 943,
                "status": "Past Due",
                "date_released": past_date,
                "maturity_date": past_date,
                "payments_made": 2,
                "term_months": 12,
            })

        resp = client.get(
            "/api/v1/admin/reports/loans?status=Past Due",
            headers=auth_header(admin_token),
        )
        loans = resp.get_json()["loans"]
        past_due = [l for l in loans if l["loan_id"] == "LN-TEST-PASTDUE"]
        assert past_due
        assert past_due[0]["days_overdue"] >= 10

        with app.app_context():
            db.loans.delete_one({"loan_id": "LN-TEST-PASTDUE"})

    # ---- Savings report ----

    def test_savings_report_structure(self, client, admin_token):
        resp = client.get(
            "/api/v1/admin/reports/savings",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert "total_accounts" in body
        assert "total_deposits" in body
        assert "summary_by_product" in body
        assert "accounts" in body

    def test_savings_report_filter_by_product(self, client, admin_token):
        resp = client.get(
            "/api/v1/admin/reports/savings?product_type=Regular Savings",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        for acct in resp.get_json()["accounts"]:
            assert acct["product_type"] == "Regular Savings"

    def test_savings_report_excludes_closed(self, client, admin_token):
        for acct in client.get(
            "/api/v1/admin/reports/savings", headers=auth_header(admin_token)
        ).get_json()["accounts"]:
            assert acct["status"] != "Closed"

    # ---- Shares report ----

    def test_shares_report_structure(self, client, admin_token):
        resp = client.get(
            "/api/v1/admin/reports/shares",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        for key in ("total_members", "members_with_paid_shares",
                    "total_subscribed_amount", "total_paid_amount",
                    "total_outstanding_amount", "records"):
            assert key in body

    def test_shares_report_totals_are_numbers(self, client, admin_token):
        body = client.get(
            "/api/v1/admin/reports/shares", headers=auth_header(admin_token)
        ).get_json()
        assert isinstance(body["total_paid_amount"], (int, float))
        assert isinstance(body["total_subscribed_amount"], (int, float))

    def test_reports_require_auth(self, client):
        for endpoint in ("members", "loans", "savings", "shares"):
            assert client.get(f"/api/v1/admin/reports/{endpoint}").status_code == 401