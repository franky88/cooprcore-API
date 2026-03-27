# backend/tests/test_savings.py
import pytest
from tests.conftest import auth_header
from tests.fixtures.member_fixtures import valid_member_payload
from tests.fixtures.savings_fixtures import (
    open_account_payload,
    deposit_payload,
    withdrawal_payload,
)


# ------------------------------------------------------------------ #
# Session-scoped member shared by all savings tests
# ------------------------------------------------------------------ #

@pytest.fixture(scope="module")
def test_member(client, admin_token, app, db):
    resp = client.post(
        "/api/v1/members",
        json=valid_member_payload({"phone": "09170000077", "email": "savingstest@email.com"}),
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 201
    member = resp.get_json()
    yield member

    with app.app_context():
        mid = member["member_id"]
        db.members.delete_one({"member_id": mid})
        db.savings_accounts.delete_many({"member_id": mid})
        db.savings_transactions.delete_many({"member_id": mid})
        db.share_capital.delete_many({"member_id": mid})


def _open(client, token, member_id, overrides=None):
    return client.post(
        "/api/v1/savings",
        json=open_account_payload(member_id, overrides),
        headers=auth_header(token),
    )


def _cleanup_account(app, db, account_id: str):
    with app.app_context():
        db.savings_accounts.delete_one({"account_id": account_id})
        db.savings_transactions.delete_many({"account_id": account_id})


# ------------------------------------------------------------------ #
# List accounts
# ------------------------------------------------------------------ #

class TestListAccounts:

    def test_list_requires_auth(self, client):
        assert client.get("/api/v1/savings").status_code == 401

    def test_list_returns_envelope(self, client, admin_token):
        resp = client.get("/api/v1/savings", headers=auth_header(admin_token))
        assert resp.status_code == 200
        body = resp.get_json()
        assert "data" in body and "pagination" in body

    def test_list_filter_by_member(self, client, admin_token, test_member):
        resp = client.get(
            f"/api/v1/savings?member_id={test_member['member_id']}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        for acct in resp.get_json()["data"]:
            assert acct["member_id"] == test_member["member_id"]

    def test_list_filter_by_product_type(self, client, admin_token):
        resp = client.get(
            "/api/v1/savings?product_type=Regular Savings",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        for acct in resp.get_json()["data"]:
            assert acct["product_type"] == "Regular Savings"

    def test_list_filter_by_status(self, client, admin_token):
        resp = client.get(
            "/api/v1/savings?status=Active",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        for acct in resp.get_json()["data"]:
            assert acct["status"] == "Active"

    def test_list_accessible_to_cashier(self, client, cashier_token):
        assert client.get(
            "/api/v1/savings", headers=auth_header(cashier_token)
        ).status_code == 200


# ------------------------------------------------------------------ #
# Open account (POST /savings)
# ------------------------------------------------------------------ #

class TestOpenAccount:

    def test_open_regular_savings_success(self, client, admin_token, test_member, app, db):
        resp = _open(client, admin_token, test_member["member_id"],
                     {"passbook_number": "PB-RS-001"})
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["account_id"].startswith("SA-")
        assert body["product_type"] == "Regular Savings"
        assert body["status"] == "Active"
        assert body["current_balance"] == 500.0
        assert body["interest_rate"] == 3.0
        _cleanup_account(app, db, body["account_id"])

    def test_open_special_savings(self, client, admin_token, test_member, app, db):
        resp = _open(client, admin_token, test_member["member_id"], {
            "product_type": "Special Savings",
            "initial_deposit": 1000.0,
            "passbook_number": "PB-SS-001",
        })
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["interest_rate"] == 4.0
        _cleanup_account(app, db, body["account_id"])

    def test_open_time_deposit_success(self, client, admin_token, test_member, app, db):
        resp = _open(client, admin_token, test_member["member_id"], {
            "product_type": "Time Deposit",
            "initial_deposit": 10000.0,
            "term_months": 12,
            "placement_amount": 10000.0,
        })
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["interest_rate"] == 5.0
        assert body["maturity_date"] is not None
        _cleanup_account(app, db, body["account_id"])

    def test_open_time_deposit_missing_term(self, client, admin_token, test_member):
        resp = _open(client, admin_token, test_member["member_id"], {
            "product_type": "Time Deposit",
            "placement_amount": 10000.0,
        })
        assert resp.status_code == 400

    def test_open_initial_deposit_creates_transaction(self, client, admin_token, test_member, app, db):
        resp = _open(client, admin_token, test_member["member_id"],
                     {"initial_deposit": 750.0, "passbook_number": "PB-TXN-001"})
        account_id = resp.get_json()["account_id"]

        with app.app_context():
            txn = db.savings_transactions.find_one({"account_id": account_id})
            assert txn is not None
            assert txn["transaction_type"] == "Deposit"
            assert txn["amount"] == 750.0

        _cleanup_account(app, db, account_id)

    def test_open_zero_initial_deposit_no_transaction(self, client, admin_token, test_member, app, db):
        resp = _open(client, admin_token, test_member["member_id"],
                     {"initial_deposit": 0.0, "passbook_number": "PB-ZERO-001"})
        account_id = resp.get_json()["account_id"]

        with app.app_context():
            count = db.savings_transactions.count_documents({"account_id": account_id})
            assert count == 0

        _cleanup_account(app, db, account_id)

    def test_open_unknown_member(self, client, admin_token):
        resp = client.post(
            "/api/v1/savings",
            json=open_account_payload("M-0000-9999"),
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_open_invalid_product_type(self, client, admin_token, test_member):
        resp = _open(client, admin_token, test_member["member_id"],
                     {"product_type": "VIP Savings"})
        assert resp.status_code == 400

    def test_open_requires_manager_or_admin(self, client, cashier_token, test_member):
        resp = _open(client, cashier_token, test_member["member_id"])
        assert resp.status_code == 403

    def test_open_requires_auth(self, client, test_member):
        resp = client.post(
            "/api/v1/savings",
            json=open_account_payload(test_member["member_id"]),
        )
        assert resp.status_code == 401


# ------------------------------------------------------------------ #
# Get account
# ------------------------------------------------------------------ #

class TestGetAccount:

    @pytest.fixture(autouse=True)
    def setup_account(self, client, admin_token, test_member, app, db):
        resp = _open(client, admin_token, test_member["member_id"],
                     {"passbook_number": "PB-GET-001"})
        self.account = resp.get_json()
        yield
        _cleanup_account(app, db, self.account["account_id"])

    def test_get_account_success(self, client, admin_token):
        resp = client.get(
            f"/api/v1/savings/{self.account['account_id']}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.get_json()["account_id"] == self.account["account_id"]

    def test_get_account_not_found(self, client, admin_token):
        resp = client.get(
            "/api/v1/savings/SA-0000-9999",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404

    def test_get_account_accessible_to_cashier(self, client, cashier_token):
        resp = client.get(
            f"/api/v1/savings/{self.account['account_id']}",
            headers=auth_header(cashier_token),
        )
        assert resp.status_code == 200


# ------------------------------------------------------------------ #
# Update account
# ------------------------------------------------------------------ #

class TestUpdateAccount:

    @pytest.fixture(autouse=True)
    def setup_account(self, client, admin_token, test_member, app, db):
        resp = _open(client, admin_token, test_member["member_id"],
                     {"passbook_number": "PB-UPD-001"})
        self.account = resp.get_json()
        yield
        _cleanup_account(app, db, self.account["account_id"])

    def test_update_passbook_number(self, client, admin_token):
        resp = client.put(
            f"/api/v1/savings/{self.account['account_id']}",
            json={"passbook_number": "PB-UPDATED"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.get_json()["passbook_number"] == "PB-UPDATED"

    def test_update_status_to_dormant(self, client, admin_token):
        resp = client.put(
            f"/api/v1/savings/{self.account['account_id']}",
            json={"status": "Dormant"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "Dormant"

    def test_update_invalid_status(self, client, admin_token):
        resp = client.put(
            f"/api/v1/savings/{self.account['account_id']}",
            json={"status": "Frozen"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_update_requires_manager(self, client, cashier_token):
        resp = client.put(
            f"/api/v1/savings/{self.account['account_id']}",
            json={"passbook_number": "HACK"},
            headers=auth_header(cashier_token),
        )
        assert resp.status_code == 403


# ------------------------------------------------------------------ #
# Post transaction (deposit / withdrawal)
# ------------------------------------------------------------------ #

class TestPostTransaction:

    @pytest.fixture(autouse=True)
    def setup_account(self, client, admin_token, test_member, app, db):
        resp = _open(client, admin_token, test_member["member_id"], {
            "initial_deposit": 1000.0,
            "passbook_number": "PB-TXN-TEST-001",
        })
        self.account = resp.get_json()
        yield
        _cleanup_account(app, db, self.account["account_id"])

    def _post(self, client, token, payload):
        return client.post(
            f"/api/v1/savings/{self.account['account_id']}/transactions",
            json=payload,
            headers=auth_header(token),
        )

    def test_deposit_success(self, client, admin_token):
        resp = self._post(client, admin_token, deposit_payload())
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["transaction_type"] == "Deposit"
        assert body["balance_after"] == 2000.0
        assert "transaction_id" in body

    def test_deposit_updates_account_balance(self, client, admin_token):
        self._post(client, admin_token, deposit_payload({"or_number": "OR-BAL-001"}))
        acct = client.get(
            f"/api/v1/savings/{self.account['account_id']}",
            headers=auth_header(admin_token),
        ).get_json()
        assert acct["current_balance"] == 2000.0

    def test_withdrawal_success(self, client, admin_token):
        resp = self._post(client, admin_token, withdrawal_payload())
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["transaction_type"] == "Withdrawal"
        assert body["balance_after"] == 800.0

    def test_withdrawal_insufficient_balance(self, client, admin_token):
        resp = self._post(
            client, admin_token,
            withdrawal_payload({"amount": 9999.0, "or_number": "OR-INSUF-001"}),
        )
        assert resp.status_code == 400
        assert "Insufficient balance" in resp.get_json()["error"]

    def test_withdrawal_exact_balance(self, client, admin_token):
        """Withdrawing exactly the full balance should succeed."""
        resp = self._post(
            client, admin_token,
            withdrawal_payload({"amount": 1000.0, "or_number": "OR-EXACT-001"}),
        )
        assert resp.status_code == 201
        assert resp.get_json()["balance_after"] == 0.0

    def test_transaction_missing_or_number(self, client, admin_token):
        p = deposit_payload()
        p.pop("or_number")
        assert self._post(client, admin_token, p).status_code == 400

    def test_transaction_invalid_type(self, client, admin_token):
        resp = self._post(
            client, admin_token,
            {**deposit_payload(), "transaction_type": "Interest"},
        )
        assert resp.status_code == 400

    def test_transaction_zero_amount(self, client, admin_token):
        resp = self._post(
            client, admin_token,
            deposit_payload({"amount": 0.0, "or_number": "OR-ZERO-001"}),
        )
        assert resp.status_code == 400

    def test_transaction_on_closed_account(self, client, admin_token):
        client.put(
            f"/api/v1/savings/{self.account['account_id']}",
            json={"status": "Closed"},
            headers=auth_header(admin_token),
        )
        resp = self._post(client, admin_token, deposit_payload({"or_number": "OR-CLOSED-001"}))
        assert resp.status_code == 400
        assert "Closed" in resp.get_json()["error"]
        # Reopen for fixture teardown
        client.put(
            f"/api/v1/savings/{self.account['account_id']}",
            json={"status": "Active"},
            headers=auth_header(admin_token),
        )

    def test_transaction_on_dormant_account(self, client, admin_token):
        client.put(
            f"/api/v1/savings/{self.account['account_id']}",
            json={"status": "Dormant"},
            headers=auth_header(admin_token),
        )
        resp = self._post(client, admin_token, deposit_payload({"or_number": "OR-DORM-001"}))
        assert resp.status_code == 400
        assert "Dormant" in resp.get_json()["error"]
        client.put(
            f"/api/v1/savings/{self.account['account_id']}",
            json={"status": "Active"},
            headers=auth_header(admin_token),
        )

    def test_transaction_requires_cashier_or_above(self, client, cashier_token):
        resp = self._post(
            client, cashier_token,
            deposit_payload({"or_number": "OR-CASHIER-001"}),
        )
        assert resp.status_code == 201

    def test_transaction_loan_officer_blocked(self, client, app, db):
        from app.services.user_service import UserService
        with app.app_context():
            UserService().create_user({
                "full_name": "Test Officer Savings",
                "email": "testofficer_savings@coopcore.ph",
                "password": "Officer@1234",
                "role": "loan_officer",
            }, created_by="test")
        lo_resp = client.post("/api/v1/auth/login",
                              json={"email": "testofficer_savings@coopcore.ph",
                                    "password": "Officer@1234"})
        lo_token = lo_resp.get_json()["access_token"]

        resp = self._post(client, lo_token,
                          deposit_payload({"or_number": "OR-LO-001"}))
        assert resp.status_code == 403

        with app.app_context():
            db.users.delete_one({"email": "testofficer_savings@coopcore.ph"})

    def test_transaction_requires_auth(self, client):
        resp = client.post(
            f"/api/v1/savings/{self.account['account_id']}/transactions",
            json=deposit_payload(),
        )
        assert resp.status_code == 401


# ------------------------------------------------------------------ #
# Ledger
# ------------------------------------------------------------------ #

class TestLedger:

    @pytest.fixture(autouse=True)
    def setup_account_with_transactions(self, client, admin_token, test_member, app, db):
        resp = _open(client, admin_token, test_member["member_id"], {
            "initial_deposit": 2000.0,
            "passbook_number": "PB-LEDGER-001",
        })
        self.account = resp.get_json()
        account_id = self.account["account_id"]

        # Post 3 deposits
        for i in range(3):
            client.post(
                f"/api/v1/savings/{account_id}/transactions",
                json=deposit_payload({"amount": 500.0, "or_number": f"OR-L-{i:03d}"}),
                headers=auth_header(admin_token),
            )
        yield
        _cleanup_account(app, db, account_id)

    def test_ledger_returns_transactions(self, client, admin_token):
        resp = client.get(
            f"/api/v1/savings/{self.account['account_id']}/ledger",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert "data" in body
        assert "pagination" in body
        assert "account" in body
        # 1 initial deposit + 3 deposits = 4
        assert body["pagination"]["total"] == 4

    def test_ledger_not_found(self, client, admin_token):
        resp = client.get(
            "/api/v1/savings/SA-0000-9999/ledger",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404

    def test_ledger_pagination(self, client, admin_token):
        resp = client.get(
            f"/api/v1/savings/{self.account['account_id']}/ledger?page=1&per_page=2",
            headers=auth_header(admin_token),
        )
        body = resp.get_json()
        assert len(body["data"]) == 2
        assert body["pagination"]["per_page"] == 2


# ------------------------------------------------------------------ #
# Interest posting
# ------------------------------------------------------------------ #

class TestPostInterest:

    @pytest.fixture(autouse=True)
    def setup_account(self, client, admin_token, test_member, app, db):
        resp = _open(client, admin_token, test_member["member_id"], {
            "initial_deposit": 12000.0,
            "passbook_number": "PB-INT-001",
        })
        self.account = resp.get_json()
        yield
        _cleanup_account(app, db, self.account["account_id"])

    def test_post_interest_to_single_account(self, client, admin_token):
        resp = client.post(
            "/api/v1/savings/interest",
            json={"account_id": self.account["account_id"]},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["processed"] == 1
        assert body["skipped"] == 0
        detail = body["details"][0]
        assert "gross_interest" in detail
        assert "tax_withheld" in detail
        assert "net_interest" in detail
        assert detail["net_interest"] < detail["gross_interest"]

    def test_interest_computation_correctness(self, client, admin_token, app, db):
        """
        ₱12,000 @ 3% p.a. → monthly gross = ₱30.00
        20% withholding tax → ₱6.00
        Net = ₱24.00
        """
        client.post(
            "/api/v1/savings/interest",
            json={"account_id": self.account["account_id"]},
            headers=auth_header(admin_token),
        )
        with app.app_context():
            acct = db.savings_accounts.find_one(
                {"account_id": self.account["account_id"]}
            )
            assert abs(acct["current_balance"] - 12024.0) < 0.05

    def test_interest_not_posted_twice_same_month(self, client, admin_token):
        client.post(
            "/api/v1/savings/interest",
            json={"account_id": self.account["account_id"]},
            headers=auth_header(admin_token),
        )
        # Second call in the same month
        resp = client.post(
            "/api/v1/savings/interest",
            json={"account_id": self.account["account_id"]},
            headers=auth_header(admin_token),
        )
        body = resp.get_json()
        assert body["skipped"] == 1
        assert body["processed"] == 0

    def test_interest_requires_manager_or_admin(self, client, cashier_token):
        resp = client.post(
            "/api/v1/savings/interest",
            json={"account_id": self.account["account_id"]},
            headers=auth_header(cashier_token),
        )
        assert resp.status_code == 403

    def test_interest_by_product_type(self, client, admin_token, test_member, app, db):
        # Open a second account for this sub-test
        r = _open(client, admin_token, test_member["member_id"], {
            "product_type": "Special Savings",
            "initial_deposit": 5000.0,
            "passbook_number": "PB-SS-INT-001",
        })
        second_account_id = r.get_json()["account_id"]

        resp = client.post(
            "/api/v1/savings/interest",
            json={"product_type": "Special Savings"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.get_json()["processed"] >= 1

        _cleanup_account(app, db, second_account_id)


# ------------------------------------------------------------------ #
# Dormancy check
# ------------------------------------------------------------------ #

class TestDormancyCheck:

    def test_dormancy_check_returns_count(self, client, admin_token):
        resp = client.post(
            "/api/v1/savings/dormancy-check",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert "accounts_marked_dormant" in resp.get_json()

    def test_dormancy_check_requires_manager(self, client, cashier_token):
        resp = client.post(
            "/api/v1/savings/dormancy-check",
            headers=auth_header(cashier_token),
        )
        assert resp.status_code == 403