# backend/tests/test_members.py
import pytest
from tests.conftest import auth_header
from tests.fixtures.member_fixtures import valid_member_payload


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def create_member(client, token: str, overrides: dict | None = None) -> dict:
    """Helper: POST /members and return the response body."""
    resp = client.post(
        "/api/v1/members",
        json=valid_member_payload(overrides),
        headers=auth_header(token),
    )
    return resp


def cleanup_member(app, db, member_id: str) -> None:
    """Remove test member and all auto-provisioned records."""
    with app.app_context():
        db.members.delete_one({"member_id": member_id})
        db.savings_accounts.delete_many({"member_id": member_id})
        db.share_capital.delete_many({"member_id": member_id})
        db.audit_logs.delete_many({"resource_id": member_id})


# ------------------------------------------------------------------ #
# GET /members (list)
# ------------------------------------------------------------------ #

class TestListMembers:

    def test_list_requires_auth(self, client):
        resp = client.get("/api/v1/members")
        assert resp.status_code == 401

    def test_list_accessible_to_all_roles(self, client, admin_token, manager_token, cashier_token):
        for token in (admin_token, manager_token, cashier_token):
            resp = client.get("/api/v1/members", headers=auth_header(token))
            assert resp.status_code == 200

    def test_list_returns_pagination_envelope(self, client, admin_token):
        resp = client.get("/api/v1/members", headers=auth_header(admin_token))
        body = resp.get_json()
        assert "data" in body
        assert "pagination" in body
        pagination = body["pagination"]
        for key in ("page", "per_page", "total", "pages"):
            assert key in pagination

    def test_list_filter_by_status(self, client, admin_token):
        resp = client.get(
            "/api/v1/members?status=Active", headers=auth_header(admin_token)
        )
        assert resp.status_code == 200
        body = resp.get_json()
        for m in body["data"]:
            assert m["status"] == "Active"

    def test_list_filter_by_membership_type(self, client, admin_token):
        resp = client.get(
            "/api/v1/members?membership_type=Regular",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        for m in resp.get_json()["data"]:
            assert m["membership_type"] == "Regular"

    def test_list_per_page_capped_at_100(self, client, admin_token):
        resp = client.get(
            "/api/v1/members?per_page=9999", headers=auth_header(admin_token)
        )
        assert resp.get_json()["pagination"]["per_page"] <= 100


# ------------------------------------------------------------------ #
# POST /members (create)
# ------------------------------------------------------------------ #

class TestCreateMember:

    def test_create_success(self, client, admin_token, app, db):
        resp = create_member(client, admin_token)
        assert resp.status_code == 201
        body = resp.get_json()

        assert body["member_id"].startswith("M-")
        assert body["status"] == "Active"
        assert body["first_name"] == "Juan"
        assert "password_hash" not in body

        # Auto-provisioned savings account must exist
        with app.app_context():
            sa = db.savings_accounts.find_one({"member_id": body["member_id"]})
            assert sa is not None
            assert sa["product_type"] == "Regular Savings"
            assert sa["current_balance"] == 0.0

            # Auto-provisioned share capital record must exist
            sc = db.share_capital.find_one({"member_id": body["member_id"]})
            assert sc is not None
            assert sc["paid_shares"] == 0

        cleanup_member(app, db, body["member_id"])

    def test_create_requires_write_role(self, client, cashier_token):
        resp = create_member(client, cashier_token)
        assert resp.status_code == 403

    def test_create_requires_auth(self, client):
        resp = client.post("/api/v1/members", json=valid_member_payload())
        assert resp.status_code == 401

    def test_create_duplicate_phone(self, client, admin_token, app, db):
        resp1 = create_member(client, admin_token)
        assert resp1.status_code == 201
        member_id = resp1.get_json()["member_id"]

        resp2 = create_member(
            client, admin_token, {"email": "other@email.com"}
        )
        assert resp2.status_code == 400
        assert "phone" in resp2.get_json()["error"]

        cleanup_member(app, db, member_id)

    def test_create_duplicate_email(self, client, admin_token, app, db):
        resp1 = create_member(client, admin_token)
        assert resp1.status_code == 201
        member_id = resp1.get_json()["member_id"]

        resp2 = create_member(
            client, admin_token, {"phone": "09179999999"}
        )
        assert resp2.status_code == 400
        assert "email" in resp2.get_json()["error"]

        cleanup_member(app, db, member_id)

    def test_create_missing_required_fields(self, client, admin_token):
        resp = client.post(
            "/api/v1/members",
            json={"first_name": "Incomplete"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_create_underage_member(self, client, admin_token):
        resp = create_member(
            client, admin_token, {"date_of_birth": "2015-01-01"}
        )
        assert resp.status_code == 400
        assert "date_of_birth" in resp.get_json()["error"]

    def test_create_invalid_phone_format(self, client, admin_token):
        resp = create_member(client, admin_token, {"phone": "1234567"})
        assert resp.status_code == 400
        assert "phone" in resp.get_json()["error"]

    def test_create_invalid_tin_format(self, client, admin_token):
        resp = create_member(client, admin_token, {"tin": "notatin"})
        assert resp.status_code == 400
        assert "tin" in resp.get_json()["error"]

    def test_create_invalid_zip_code(self, client, admin_token):
        payload = valid_member_payload()
        payload["address"]["zip_code"] = "ABCD"
        resp = client.post(
            "/api/v1/members",
            json=payload,
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_create_invalid_membership_type(self, client, admin_token):
        resp = create_member(client, admin_token, {"membership_type": "VIP"})
        assert resp.status_code == 400

    def test_create_invalid_gender(self, client, admin_token):
        resp = create_member(client, admin_token, {"gender": "Unknown"})
        assert resp.status_code == 400

    def test_create_member_id_format(self, client, admin_token, app, db):
        resp = create_member(client, admin_token)
        body = resp.get_json()
        # M-YYYY-NNNN
        import re
        assert re.match(r"^M-\d{4}-\d{4}$", body["member_id"])
        cleanup_member(app, db, body["member_id"])

    def test_create_without_optional_fields(self, client, admin_token, app, db):
        """email, tin, employer, occupation are all optional."""
        payload = valid_member_payload()
        payload.pop("email")
        payload.pop("tin")
        payload.pop("employer")
        payload.pop("occupation")
        payload["phone"] = "09170000001"
        resp = client.post(
            "/api/v1/members",
            json=payload,
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 201
        cleanup_member(app, db, resp.get_json()["member_id"])


# ------------------------------------------------------------------ #
# GET /members/<member_id>
# ------------------------------------------------------------------ #

class TestGetMember:

    @pytest.fixture(autouse=True)
    def setup_member(self, client, admin_token, app, db):
        resp = create_member(client, admin_token)
        self.member = resp.get_json()
        yield
        cleanup_member(app, db, self.member["member_id"])

    def test_get_member_success(self, client, admin_token):
        resp = client.get(
            f"/api/v1/members/{self.member['member_id']}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["member_id"] == self.member["member_id"]
        assert "password_hash" not in body

    def test_get_member_not_found(self, client, admin_token):
        resp = client.get(
            "/api/v1/members/M-0000-9999",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404

    def test_get_member_accessible_to_cashier(self, client, cashier_token):
        resp = client.get(
            f"/api/v1/members/{self.member['member_id']}",
            headers=auth_header(cashier_token),
        )
        assert resp.status_code == 200

    def test_get_member_requires_auth(self, client):
        resp = client.get(f"/api/v1/members/{self.member['member_id']}")
        assert resp.status_code == 401


# ------------------------------------------------------------------ #
# GET /members/<member_id>/summary
# ------------------------------------------------------------------ #

class TestMemberSummary:

    @pytest.fixture(autouse=True)
    def setup_member(self, client, admin_token, app, db):
        resp = create_member(client, admin_token)
        self.member = resp.get_json()
        yield
        cleanup_member(app, db, self.member["member_id"])

    def test_summary_structure(self, client, admin_token):
        resp = client.get(
            f"/api/v1/members/{self.member['member_id']}/summary",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert "member" in body
        assert "loans" in body
        assert "savings" in body
        assert "shares" in body
        assert "totals" in body

    def test_summary_totals_keys(self, client, admin_token):
        body = client.get(
            f"/api/v1/members/{self.member['member_id']}/summary",
            headers=auth_header(admin_token),
        ).get_json()
        totals = body["totals"]
        assert "total_outstanding_loans" in totals
        assert "total_savings_balance" in totals
        assert "active_loan_count" in totals

    def test_summary_new_member_has_savings(self, client, admin_token):
        body = client.get(
            f"/api/v1/members/{self.member['member_id']}/summary",
            headers=auth_header(admin_token),
        ).get_json()
        assert len(body["savings"]) == 1
        assert body["savings"][0]["product_type"] == "Regular Savings"

    def test_summary_new_member_has_share_record(self, client, admin_token):
        body = client.get(
            f"/api/v1/members/{self.member['member_id']}/summary",
            headers=auth_header(admin_token),
        ).get_json()
        assert body["shares"] is not None
        assert body["shares"]["paid_shares"] == 0

    def test_summary_not_found(self, client, admin_token):
        resp = client.get(
            "/api/v1/members/M-0000-9999/summary",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404


# ------------------------------------------------------------------ #
# PUT /members/<member_id>
# ------------------------------------------------------------------ #

class TestUpdateMember:

    @pytest.fixture(autouse=True)
    def setup_member(self, client, admin_token, app, db):
        resp = create_member(client, admin_token)
        self.member = resp.get_json()
        yield
        cleanup_member(app, db, self.member["member_id"])

    def test_update_success(self, client, admin_token):
        resp = client.put(
            f"/api/v1/members/{self.member['member_id']}",
            json={"employer": "New Corp", "occupation": "Manager", "monthly_income": 50000},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["employer"] == "New Corp"
        assert body["monthly_income"] == 50000

    def test_update_status(self, client, admin_token):
        resp = client.put(
            f"/api/v1/members/{self.member['member_id']}",
            json={"status": "Suspended"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "Suspended"

    def test_update_invalid_status(self, client, admin_token):
        resp = client.put(
            f"/api/v1/members/{self.member['member_id']}",
            json={"status": "Banned"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_update_phone_to_existing_phone(self, client, admin_token, app, db):
        # Create a second member with a different phone
        resp2 = create_member(
            client,
            admin_token,
            {"phone": "09179999888", "email": "other2@email.com"},
        )
        member2 = resp2.get_json()

        # Try to update member1's phone to member2's phone
        resp = client.put(
            f"/api/v1/members/{self.member['member_id']}",
            json={"phone": "09179999888"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400
        assert "phone" in resp.get_json()["error"]

        cleanup_member(app, db, member2["member_id"])

    def test_update_name_syncs_denormalized_fields(self, client, admin_token, app, db):
        client.put(
            f"/api/v1/members/{self.member['member_id']}",
            json={"last_name": "Reyes"},
            headers=auth_header(admin_token),
        )
        with app.app_context():
            sa = db.savings_accounts.find_one({"member_id": self.member["member_id"]})
            assert "Reyes" in sa["member_name"]

    def test_update_requires_write_role(self, client, cashier_token):
        resp = client.put(
            f"/api/v1/members/{self.member['member_id']}",
            json={"occupation": "Hacked"},
            headers=auth_header(cashier_token),
        )
        assert resp.status_code == 403

    def test_update_not_found(self, client, admin_token):
        resp = client.put(
            "/api/v1/members/M-0000-9999",
            json={"occupation": "Ghost"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()