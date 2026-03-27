# backend/tests/test_users.py
import pytest
from tests.conftest import auth_header


class TestListUsers:

    def test_list_users_as_admin(self, client, admin_token):
        resp = client.get("/api/v1/users", headers=auth_header(admin_token))
        assert resp.status_code == 200
        body = resp.get_json()
        assert "data" in body
        assert "pagination" in body
        assert isinstance(body["data"], list)

    def test_list_users_forbidden_for_manager(self, client, manager_token):
        resp = client.get("/api/v1/users", headers=auth_header(manager_token))
        assert resp.status_code == 403

    def test_list_users_forbidden_for_cashier(self, client, cashier_token):
        resp = client.get("/api/v1/users", headers=auth_header(cashier_token))
        assert resp.status_code == 403

    def test_list_users_requires_auth(self, client):
        resp = client.get("/api/v1/users")
        assert resp.status_code == 401

    def test_list_users_filter_by_role(self, client, admin_token):
        resp = client.get(
            "/api/v1/users?role=cashier", headers=auth_header(admin_token)
        )
        assert resp.status_code == 200
        body = resp.get_json()
        for user in body["data"]:
            assert user["role"] == "cashier"

    def test_list_users_search(self, client, admin_token):
        resp = client.get(
            "/api/v1/users?search=testadmin", headers=auth_header(admin_token)
        )
        assert resp.status_code == 200
        body = resp.get_json()
        # Should find at least our test admin
        assert body["pagination"]["total"] >= 1

    def test_list_users_pagination(self, client, admin_token):
        resp = client.get(
            "/api/v1/users?page=1&per_page=2", headers=auth_header(admin_token)
        )
        body = resp.get_json()
        assert resp.status_code == 200
        assert body["pagination"]["per_page"] == 2
        assert len(body["data"]) <= 2

    def test_per_page_hard_cap(self, client, admin_token):
        resp = client.get(
            "/api/v1/users?per_page=9999", headers=auth_header(admin_token)
        )
        body = resp.get_json()
        assert resp.status_code == 200
        assert body["pagination"]["per_page"] <= 100


class TestCreateUser:

    def _valid_payload(self, suffix: str = "01") -> dict:
        return {
            "full_name": f"New User {suffix}",
            "email": f"newuser{suffix}@coopcore.ph",
            "password": "NewUser@1234",
            "role": "loan_officer",
            "branch": "South Branch",
        }

    def test_create_user_success(self, client, admin_token, app, db):
        payload = self._valid_payload("A1")
        resp = client.post(
            "/api/v1/users",
            json=payload,
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["email"] == payload["email"]
        assert body["role"] == "loan_officer"
        assert "password_hash" not in body
        assert "password" not in body
        assert body["employee_id"].startswith("EMP-")

        # Cleanup
        with app.app_context():
            db.users.delete_one({"email": payload["email"]})

    def test_create_user_duplicate_email(self, client, admin_token):
        resp = client.post(
            "/api/v1/users",
            json={
                "full_name": "Duplicate",
                "email": "testadmin@coopcore.ph",  # already exists
                "password": "Dup@12345",
                "role": "cashier",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400
        assert "email" in resp.get_json()["error"]

    def test_create_user_invalid_role(self, client, admin_token):
        resp = client.post(
            "/api/v1/users",
            json={
                "full_name": "Bad Role",
                "email": "badrole@coopcore.ph",
                "password": "Bad@12345",
                "role": "hacker",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_create_user_weak_password(self, client, admin_token):
        resp = client.post(
            "/api/v1/users",
            json={
                "full_name": "Weak Pass",
                "email": "weakpass@coopcore.ph",
                "password": "weak",
                "role": "cashier",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_create_user_missing_required_fields(self, client, admin_token):
        resp = client.post(
            "/api/v1/users",
            json={"full_name": "No Email"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_create_user_forbidden_for_non_admin(self, client, manager_token):
        resp = client.post(
            "/api/v1/users",
            json=self._valid_payload("B2"),
            headers=auth_header(manager_token),
        )
        assert resp.status_code == 403


class TestGetUser:

    def _get_test_admin_id(self, client, admin_token) -> str:
        users = client.get(
            "/api/v1/users?search=testadmin", headers=auth_header(admin_token)
        ).get_json()["data"]
        return users[0]["id"]

    def test_get_user_success(self, client, admin_token):
        user_id = self._get_test_admin_id(client, admin_token)
        resp = client.get(
            f"/api/v1/users/{user_id}", headers=auth_header(admin_token)
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert "password_hash" not in body
        assert body["id"] == user_id

    def test_get_user_not_found(self, client, admin_token):
        resp = client.get(
            "/api/v1/users/000000000000000000000000",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404

    def test_get_user_invalid_id(self, client, admin_token):
        resp = client.get(
            "/api/v1/users/not-a-valid-id",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404

    def test_get_user_forbidden_for_cashier(self, client, cashier_token):
        resp = client.get(
            "/api/v1/users/anyid", headers=auth_header(cashier_token)
        )
        assert resp.status_code == 403


class TestUpdateUser:

    def _create_temp_user(self, client, admin_token, suffix: str) -> dict:
        resp = client.post(
            "/api/v1/users",
            json={
                "full_name": f"Temp {suffix}",
                "email": f"temp{suffix}@coopcore.ph",
                "password": "Temp@1234",
                "role": "cashier",
            },
            headers=auth_header(admin_token),
        )
        return resp.get_json()

    def test_update_user_success(self, client, admin_token, app, db):
        user = self._create_temp_user(client, admin_token, "upd1")
        resp = client.put(
            f"/api/v1/users/{user['id']}",
            json={"full_name": "Updated Name", "branch": "New Branch"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.get_json()["full_name"] == "Updated Name"

        with app.app_context():
            db.users.delete_one({"email": user["email"]})

    def test_update_user_invalid_role(self, client, admin_token, app, db):
        user = self._create_temp_user(client, admin_token, "upd2")
        resp = client.put(
            f"/api/v1/users/{user['id']}",
            json={"role": "god_mode"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

        with app.app_context():
            db.users.delete_one({"email": user["email"]})

    def test_update_user_forbidden_for_manager(self, client, manager_token):
        resp = client.put(
            "/api/v1/users/anyid",
            json={"full_name": "Hack"},
            headers=auth_header(manager_token),
        )
        assert resp.status_code == 403


class TestResetPassword:

    def test_admin_reset_password_success(self, client, admin_token, app, db):
        user_resp = client.post(
            "/api/v1/users",
            json={
                "full_name": "Reset User",
                "email": "resetme@coopcore.ph",
                "password": "Reset@1234",
                "role": "cashier",
            },
            headers=auth_header(admin_token),
        )
        user = user_resp.get_json()

        resp = client.post(
            f"/api/v1/users/{user['id']}/reset-password",
            json={"new_password": "NewReset@9999"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

        # New password must work
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "resetme@coopcore.ph", "password": "NewReset@9999"},
        )
        assert login.status_code == 200

        with app.app_context():
            db.users.delete_one({"email": "resetme@coopcore.ph"})

    def test_admin_reset_weak_password(self, client, admin_token, app, db):
        user_resp = client.post(
            "/api/v1/users",
            json={
                "full_name": "Reset Weak",
                "email": "resetweak@coopcore.ph",
                "password": "Reset@1234",
                "role": "cashier",
            },
            headers=auth_header(admin_token),
        )
        user = user_resp.get_json()

        resp = client.post(
            f"/api/v1/users/{user['id']}/reset-password",
            json={"new_password": "weak"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

        with app.app_context():
            db.users.delete_one({"email": "resetweak@coopcore.ph"})

    def test_reset_password_forbidden_for_non_admin(self, client, manager_token):
        resp = client.post(
            "/api/v1/users/anyid/reset-password",
            json={"new_password": "New@12345"},
            headers=auth_header(manager_token),
        )
        assert resp.status_code == 403


class TestDeactivateUser:

    def test_deactivate_user(self, client, admin_token, app, db):
        user_resp = client.post(
            "/api/v1/users",
            json={
                "full_name": "To Deactivate",
                "email": "deactivateme@coopcore.ph",
                "password": "Deact@1234",
                "role": "cashier",
            },
            headers=auth_header(admin_token),
        )
        user = user_resp.get_json()

        resp = client.delete(
            f"/api/v1/users/{user['id']}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

        # Deactivated user must not be able to log in
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "deactivateme@coopcore.ph", "password": "Deact@1234"},
        )
        assert login.status_code == 403

        with app.app_context():
            db.users.delete_one({"email": "deactivateme@coopcore.ph"})

    def test_cannot_self_deactivate(self, client, admin_token):
        # Get own user id
        me = client.get("/api/v1/auth/me", headers=auth_header(admin_token)).get_json()
        resp = client.delete(
            f"/api/v1/users/{me['id']}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_deactivate_forbidden_for_cashier(self, client, cashier_token):
        resp = client.delete(
            "/api/v1/users/anyid", headers=auth_header(cashier_token)
        )
        assert resp.status_code == 403