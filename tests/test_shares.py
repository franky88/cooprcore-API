# backend/tests/test_shares.py
import pytest
from tests.conftest import auth_header
from tests.fixtures.member_fixtures import valid_member_payload
from tests.fixtures.share_fixtures import subscribe_payload, payment_payload, dividend_payload


# ------------------------------------------------------------------ #
# Session-scoped member
# ------------------------------------------------------------------ #

@pytest.fixture(scope="module")
def test_member(client, admin_token, app, db):
    resp = client.post(
        "/api/v1/members",
        json=valid_member_payload({"phone": "09170000055", "email": "sharetest@email.com"}),
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
        db.share_payments.delete_many({"member_id": mid})


@pytest.fixture(scope="module")
def share_record(client, admin_token, test_member):
    """Fetches the auto-provisioned share record for the test member."""
    resp = client.get(
        f"/api/v1/shares/member/{test_member['member_id']}",
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    return resp.get_json()


def _subscribe(client, token, share_id, overrides=None):
    return client.put(
        f"/api/v1/shares/{share_id}/subscribe",
        json=subscribe_payload(overrides=overrides),
        headers=auth_header(token),
    )


def _pay(client, token, share_id, overrides=None):
    return client.post(
        f"/api/v1/shares/{share_id}/payments",
        json=payment_payload(overrides=overrides),
        headers=auth_header(token),
    )


# ------------------------------------------------------------------ #
# List shares
# ------------------------------------------------------------------ #

class TestListShares:

    def test_list_requires_auth(self, client):
        assert client.get("/api/v1/shares").status_code == 401

    def test_list_returns_envelope(self, client, admin_token):
        resp = client.get("/api/v1/shares", headers=auth_header(admin_token))
        assert resp.status_code == 200
        body = resp.get_json()
        assert "data" in body and "pagination" in body

    def test_list_accessible_to_cashier(self, client, cashier_token):
        assert client.get(
            "/api/v1/shares", headers=auth_header(cashier_token)
        ).status_code == 200

    def test_list_filter_by_member(self, client, admin_token, test_member):
        resp = client.get(
            f"/api/v1/shares?member_id={test_member['member_id']}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["pagination"]["total"] == 1
        assert body["data"][0]["member_id"] == test_member["member_id"]

    def test_list_search_by_member_name(self, client, admin_token, test_member):
        resp = client.get(
            f"/api/v1/shares?search={test_member['last_name']}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.get_json()["pagination"]["total"] >= 1


# ------------------------------------------------------------------ #
# Get share record
# ------------------------------------------------------------------ #

class TestGetShare:

    def test_get_by_share_id(self, client, admin_token, share_record):
        resp = client.get(
            f"/api/v1/shares/{share_record['share_id']}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.get_json()["share_id"] == share_record["share_id"]

    def test_get_by_member_id(self, client, admin_token, test_member):
        resp = client.get(
            f"/api/v1/shares/member/{test_member['member_id']}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.get_json()["member_id"] == test_member["member_id"]

    def test_get_not_found(self, client, admin_token):
        assert client.get(
            "/api/v1/shares/SH-0000-9999", headers=auth_header(admin_token)
        ).status_code == 404

    def test_get_member_not_found(self, client, admin_token):
        assert client.get(
            "/api/v1/shares/member/M-0000-9999", headers=auth_header(admin_token)
        ).status_code == 404

    def test_get_accessible_to_cashier(self, client, cashier_token, share_record):
        assert client.get(
            f"/api/v1/shares/{share_record['share_id']}",
            headers=auth_header(cashier_token),
        ).status_code == 200


# ------------------------------------------------------------------ #
# Update subscription
# ------------------------------------------------------------------ #

class TestUpdateSubscription:

    def test_subscribe_success(self, client, admin_token, share_record, app, db):
        resp = _subscribe(client, admin_token, share_record["share_id"],
                          {"additional_shares": 20})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["subscribed_shares"] == 20
        assert body["subscribed_amount"] == 2000.0
        assert body["paid_shares"] == 0         # no payment yet
        assert body["outstanding_amount"] == 2000.0

        # Reset for other tests
        with app.app_context():
            db.share_capital.update_one(
                {"share_id": share_record["share_id"]},
                {"$set": {"subscribed_shares": 0, "subscribed_amount": 0.0,
                           "outstanding_amount": 0.0, "percentage_paid": 0.0}},
            )

    def test_subscribe_accumulates(self, client, admin_token, share_record, app, db):
        _subscribe(client, admin_token, share_record["share_id"],
                   {"additional_shares": 10})
        resp = _subscribe(client, admin_token, share_record["share_id"],
                          {"additional_shares": 5})
        assert resp.status_code == 200
        assert resp.get_json()["subscribed_shares"] == 15

        with app.app_context():
            db.share_capital.update_one(
                {"share_id": share_record["share_id"]},
                {"$set": {"subscribed_shares": 0, "subscribed_amount": 0.0,
                           "outstanding_amount": 0.0, "percentage_paid": 0.0}},
            )

    def test_subscribe_zero_shares_rejected(self, client, admin_token, share_record):
        resp = _subscribe(client, admin_token, share_record["share_id"],
                          {"additional_shares": 0})
        assert resp.status_code == 400

    def test_subscribe_negative_shares_rejected(self, client, admin_token, share_record):
        resp = _subscribe(client, admin_token, share_record["share_id"],
                          {"additional_shares": -5})
        assert resp.status_code == 400

    def test_subscribe_requires_write_role(self, client, cashier_token, share_record):
        resp = _subscribe(client, cashier_token, share_record["share_id"],
                          {"additional_shares": 10})
        assert resp.status_code == 403

    def test_subscribe_not_found(self, client, admin_token):
        resp = client.put(
            "/api/v1/shares/SH-0000-9999/subscribe",
            json=subscribe_payload(),
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_subscribe_inactive_member(self, client, admin_token, app, db):
        # Create a separate member, suspend them, then try to subscribe
        m_resp = client.post(
            "/api/v1/members",
            json=valid_member_payload(
                {"phone": "09170000033", "email": "suspended_sh@email.com"}
            ),
            headers=auth_header(admin_token),
        )
        m = m_resp.get_json()
        share = client.get(
            f"/api/v1/shares/member/{m['member_id']}",
            headers=auth_header(admin_token),
        ).get_json()

        client.put(
            f"/api/v1/members/{m['member_id']}",
            json={"status": "Suspended"},
            headers=auth_header(admin_token),
        )

        resp = client.put(
            f"/api/v1/shares/{share['share_id']}/subscribe",
            json=subscribe_payload(),
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400
        assert "not Active" in resp.get_json()["error"]

        with app.app_context():
            db.members.delete_one({"member_id": m["member_id"]})
            db.savings_accounts.delete_many({"member_id": m["member_id"]})
            db.share_capital.delete_many({"member_id": m["member_id"]})


# ------------------------------------------------------------------ #
# Record payment
# ------------------------------------------------------------------ #

class TestRecordPayment:

    @pytest.fixture(autouse=True)
    def setup_subscription(self, client, admin_token, share_record, app, db):
        """Give the test member a 50-share subscription before each test."""
        db.share_capital.update_one(
            {"share_id": share_record["share_id"]},
            {"$set": {
                "subscribed_shares": 50,
                "subscribed_amount": 5000.0,
                "paid_shares": 0,
                "paid_amount": 0.0,
                "outstanding_amount": 5000.0,
                "percentage_paid": 0.0,
            }},
        )
        self.share_id = share_record["share_id"]
        yield
        # Reset after each test
        db.share_capital.update_one(
            {"share_id": share_record["share_id"]},
            {"$set": {
                "subscribed_shares": 0, "subscribed_amount": 0.0,
                "paid_shares": 0, "paid_amount": 0.0,
                "outstanding_amount": 0.0, "percentage_paid": 0.0,
            }},
        )
        db.share_payments.delete_many({"share_id": self.share_id})

    def test_payment_success(self, client, admin_token):
        resp = _pay(client, admin_token, self.share_id,
                    {"amount_paid": 1000.0, "or_number": "OR-SH-001"})
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["payment_id"].startswith("SPY-")
        assert body["shares_paid"] == 10
        assert body["new_paid_shares"] == 10
        assert body["new_paid_amount"] == 1000.0
        assert body["outstanding_after"] == 4000.0
        assert body["percentage_paid"] == 20.0

    def test_payment_updates_share_record(self, client, admin_token):
        _pay(client, admin_token, self.share_id,
             {"amount_paid": 500.0, "or_number": "OR-SH-UPD-001"})
        record = client.get(
            f"/api/v1/shares/{self.share_id}",
            headers=auth_header(admin_token),
        ).get_json()
        assert record["paid_shares"] == 5
        assert record["paid_amount"] == 500.0
        assert record["outstanding_amount"] == 4500.0

    def test_payment_not_multiple_of_par(self, client, admin_token):
        resp = _pay(client, admin_token, self.share_id,
                    {"amount_paid": 150.0, "or_number": "OR-SH-BAD-001"})
        assert resp.status_code == 400
        assert "multiple" in resp.get_json()["error"].lower()

    def test_payment_below_minimum(self, client, admin_token):
        resp = _pay(client, admin_token, self.share_id,
                    {"amount_paid": 50.0, "or_number": "OR-SH-MIN-001"})
        assert resp.status_code == 400

    def test_payment_exceeds_outstanding(self, client, admin_token):
        resp = _pay(client, admin_token, self.share_id,
                    {"amount_paid": 9000.0, "or_number": "OR-SH-OVR-001"})
        assert resp.status_code == 400
        assert "exceeds" in resp.get_json()["error"].lower()

    def test_payment_exact_outstanding_closes_subscription(self, client, admin_token):
        """Paying exactly the outstanding amount should bring percentage_paid to 100."""
        resp = _pay(client, admin_token, self.share_id,
                    {"amount_paid": 5000.0, "or_number": "OR-SH-FULL-001"})
        assert resp.status_code == 201
        assert resp.get_json()["percentage_paid"] == 100.0
        assert resp.get_json()["outstanding_after"] == 0.0

    def test_payment_without_subscription(self, client, admin_token, app, db):
        """Cannot pay if subscribed_shares is 0."""
        # Remove subscription first
        db.share_capital.update_one(
            {"share_id": self.share_id},
            {"$set": {"subscribed_shares": 0, "subscribed_amount": 0.0,
                       "outstanding_amount": 0.0}},
        )
        resp = _pay(client, admin_token, self.share_id,
                    {"amount_paid": 1000.0, "or_number": "OR-SH-NOSUB-001"})
        assert resp.status_code == 400
        assert "subscription" in resp.get_json()["error"].lower()

    def test_payment_missing_or_number(self, client, admin_token):
        p = payment_payload()
        p.pop("or_number")
        resp = client.post(
            f"/api/v1/shares/{self.share_id}/payments",
            json=p,
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_payment_requires_cashier_or_above(self, client, cashier_token):
        resp = _pay(client, cashier_token, self.share_id,
                    {"amount_paid": 1000.0, "or_number": "OR-SH-CASHIER-001"})
        assert resp.status_code == 201

    def test_payment_loan_officer_blocked(self, client, app, db):
        from app.services.user_service import UserService
        with app.app_context():
            UserService().create_user({
                "full_name": "Test Officer Share",
                "email": "testofficer_share@coopcore.ph",
                "password": "Officer@1234",
                "role": "loan_officer",
            }, created_by="test")
        lo_token = client.post(
            "/api/v1/auth/login",
            json={"email": "testofficer_share@coopcore.ph", "password": "Officer@1234"},
        ).get_json()["access_token"]

        resp = _pay(client, lo_token, self.share_id,
                    {"amount_paid": 1000.0, "or_number": "OR-SH-LO-001"})
        assert resp.status_code == 403

        with app.app_context():
            db.users.delete_one({"email": "testofficer_share@coopcore.ph"})


# ------------------------------------------------------------------ #
# Payment history
# ------------------------------------------------------------------ #

class TestPaymentHistory:

    @pytest.fixture(autouse=True)
    def setup_payments(self, client, admin_token, share_record, app, db):
        db.share_capital.update_one(
            {"share_id": share_record["share_id"]},
            {"$set": {
                "subscribed_shares": 100, "subscribed_amount": 10000.0,
                "paid_shares": 0, "paid_amount": 0.0,
                "outstanding_amount": 10000.0, "percentage_paid": 0.0,
            }},
        )
        self.share_id = share_record["share_id"]
        for i in range(3):
            _pay(client, admin_token, self.share_id,
                 {"amount_paid": 500.0, "or_number": f"OR-HIST-{i:03d}"})
        yield
        db.share_capital.update_one(
            {"share_id": share_record["share_id"]},
            {"$set": {
                "subscribed_shares": 0, "subscribed_amount": 0.0,
                "paid_shares": 0, "paid_amount": 0.0,
                "outstanding_amount": 0.0, "percentage_paid": 0.0,
            }},
        )
        db.share_payments.delete_many({"share_id": self.share_id})

    def test_payment_history_returns_all(self, client, admin_token):
        resp = client.get(
            f"/api/v1/shares/{self.share_id}/payments",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert "share_record" in body
        assert "payments" in body
        assert len(body["payments"]) == 3

    def test_payment_history_fields(self, client, admin_token):
        body = client.get(
            f"/api/v1/shares/{self.share_id}/payments",
            headers=auth_header(admin_token),
        ).get_json()
        p = body["payments"][0]
        for field in ("payment_id", "shares_paid", "amount_paid",
                      "balance_after", "or_number", "payment_date"):
            assert field in p

    def test_payment_history_not_found(self, client, admin_token):
        assert client.get(
            "/api/v1/shares/SH-0000-9999/payments",
            headers=auth_header(admin_token),
        ).status_code == 404


# ------------------------------------------------------------------ #
# Dividend distribution
# ------------------------------------------------------------------ #

class TestDividends:

    @pytest.fixture(autouse=True)
    def setup_paid_shares(self, client, admin_token, share_record, app, db):
        """Give the member 50 subscribed + 30 paid shares before dividend tests."""
        db.share_capital.update_one(
            {"share_id": share_record["share_id"]},
            {"$set": {
                "subscribed_shares": 50, "subscribed_amount": 5000.0,
                "paid_shares": 30, "paid_amount": 3000.0,
                "outstanding_amount": 2000.0, "percentage_paid": 60.0,
            }},
        )
        self.share_id = share_record["share_id"]
        yield
        db.share_capital.update_one(
            {"share_id": share_record["share_id"]},
            {"$set": {
                "subscribed_shares": 0, "subscribed_amount": 0.0,
                "paid_shares": 0, "paid_amount": 0.0,
                "outstanding_amount": 0.0, "percentage_paid": 0.0,
            }},
        )
        db.share_payments.delete_many(
            {"share_id": self.share_id, "payment_type": "Dividend"}
        )

    def test_dividend_success(self, client, admin_token):
        resp = client.post(
            "/api/v1/shares/dividends",
            json=dividend_payload(rate=10.0, year=2091),
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["fiscal_year"] == 2091
        assert body["members_paid"] >= 1
        assert body["total_distributed"] > 0
        assert "breakdown" in body

    def test_dividend_computation(self, client, admin_token):
        """
        paid_amount = ₱3,000, rate = 10%
        Expected dividend = ₱300.00
        """
        resp = client.post(
            "/api/v1/shares/dividends",
            json=dividend_payload(rate=10.0, year=2092),
            headers=auth_header(admin_token),
        )
        body = resp.get_json()
        member_breakdown = next(
            (b for b in body["breakdown"]
             if b["member_id"] == self._get_member_id(client, admin_token)),
            None,
        )
        assert member_breakdown is not None
        assert abs(member_breakdown["dividend_amount"] - 300.0) < 0.01

    def _get_member_id(self, client, admin_token) -> str:
        return client.get(
            f"/api/v1/shares/{self.share_id}",
            headers=auth_header(admin_token),
        ).get_json()["member_id"]

    def test_dividend_idempotency(self, client, admin_token):
        """Same fiscal year cannot be processed twice."""
        client.post(
            "/api/v1/shares/dividends",
            json=dividend_payload(rate=5.0, year=2093),
            headers=auth_header(admin_token),
        )
        resp = client.post(
            "/api/v1/shares/dividends",
            json=dividend_payload(rate=5.0, year=2093),
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400
        assert "already been distributed" in resp.get_json()["error"]

    def test_dividend_missing_rate(self, client, admin_token):
        resp = client.post(
            "/api/v1/shares/dividends",
            json={"fiscal_year": 2094},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_dividend_missing_year(self, client, admin_token):
        resp = client.post(
            "/api/v1/shares/dividends",
            json={"dividend_rate": 10.0},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_dividend_rate_zero_rejected(self, client, admin_token):
        resp = client.post(
            "/api/v1/shares/dividends",
            json=dividend_payload(rate=0.0, year=2095),
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_dividend_requires_manager_or_admin(self, client, cashier_token):
        resp = client.post(
            "/api/v1/shares/dividends",
            json=dividend_payload(rate=5.0, year=2096),
            headers=auth_header(cashier_token),
        )
        assert resp.status_code == 403

    def test_dividend_requires_auth(self, client):
        resp = client.post(
            "/api/v1/shares/dividends",
            json=dividend_payload(),
        )
        assert resp.status_code == 401