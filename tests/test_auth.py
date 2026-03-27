# backend/tests/test_auth.py
import pytest
from tests.conftest import auth_header


class TestLogin:

    def test_login_success(self, client):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "testadmin@coopcore.ph", "password": "Admin@1234"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["user"]["role"] == "super_admin"
        assert "password" not in body["user"]
        assert "password_hash" not in body["user"]

    def test_login_wrong_password(self, client):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "testadmin@coopcore.ph", "password": "WrongPass@99"},
        )
        assert resp.status_code == 401
        assert "error" in resp.get_json()

    def test_login_unknown_email(self, client):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "ghost@coopcore.ph", "password": "Admin@1234"},
        )
        # Must not distinguish "user not found" from "wrong password"
        assert resp.status_code == 401

    def test_login_missing_fields(self, client):
        resp = client.post("/api/v1/auth/login", json={"email": "testadmin@coopcore.ph"})
        assert resp.status_code == 400

    def test_login_invalid_email_format(self, client):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "not-an-email", "password": "Admin@1234"},
        )
        assert resp.status_code == 400

    def test_login_empty_body(self, client):
        resp = client.post("/api/v1/auth/login", json={})
        assert resp.status_code == 400

    def test_login_no_body(self, client):
        resp = client.post("/api/v1/auth/login")
        assert resp.status_code == 400


class TestRefresh:

    def test_refresh_returns_new_access_token(self, client):
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "testadmin@coopcore.ph", "password": "Admin@1234"},
        ).get_json()

        resp = client.post(
            "/api/v1/auth/refresh",
            headers={"Authorization": f"Bearer {login['refresh_token']}"},
        )
        assert resp.status_code == 200
        assert "access_token" in resp.get_json()

    def test_refresh_rejects_access_token(self, client, admin_token):
        # Access token must not be accepted on the refresh endpoint
        resp = client.post(
            "/api/v1/auth/refresh",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    def test_refresh_missing_token(self, client):
        resp = client.post("/api/v1/auth/refresh")
        assert resp.status_code == 401


class TestMe:

    def test_me_returns_current_user(self, client, admin_token):
        resp = client.get("/api/v1/auth/me", headers=auth_header(admin_token))
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["email"] == "testadmin@coopcore.ph"
        assert "password_hash" not in body

    def test_me_requires_auth(self, client):
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401


class TestChangePassword:

    def test_change_password_success(self, client, app, db):
        # Create a throwaway user for this test
        from app.services.user_service import UserService
        with app.app_context():
            svc = UserService()
            svc.create_user(
                {
                    "full_name": "Temp User",
                    "email": "temp@coopcore.ph",
                    "password": "Temp@1234",
                    "role": "cashier",
                },
                created_by="test",
            )

        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": "temp@coopcore.ph", "password": "Temp@1234"},
        )
        token = login_resp.get_json()["access_token"]

        resp = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "Temp@1234", "new_password": "NewTemp@5678"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200

        # Old password must no longer work
        old_login = client.post(
            "/api/v1/auth/login",
            json={"email": "temp@coopcore.ph", "password": "Temp@1234"},
        )
        assert old_login.status_code == 401

        # New password must work
        new_login = client.post(
            "/api/v1/auth/login",
            json={"email": "temp@coopcore.ph", "password": "NewTemp@5678"},
        )
        assert new_login.status_code == 200

        # Cleanup
        with app.app_context():
            db.users.delete_one({"email": "temp@coopcore.ph"})

    def test_change_password_wrong_current(self, client, admin_token):
        resp = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "WrongPass@1", "new_password": "NewPass@99"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_change_password_weak_new_password(self, client, admin_token):
        resp = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "Admin@1234", "new_password": "weak"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_change_password_requires_auth(self, client):
        resp = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "Admin@1234", "new_password": "New@1234"},
        )
        assert resp.status_code == 401