# backend/tests/conftest.py
import pytest
from app import create_app
from app.services.user_service import UserService


@pytest.fixture(scope="session")
def app():
    """Create the Flask app wired to the test database."""
    application = create_app("testing")
    yield application


@pytest.fixture(scope="session")
def client(app):
    return app.test_client()


@pytest.fixture(scope="session")
def db(app):
    """Direct access to the test MongoDB database."""
    from app.extensions import mongo
    with app.app_context():
        yield mongo.db


@pytest.fixture(scope="session", autouse=True)
def seed_test_users(app, db):
    """
    Create the minimum set of users needed for auth tests.
    Runs once per session; tears down after all tests complete.
    """
    service = UserService()
    with app.app_context():
        users = [
            {
                "full_name": "Test Admin",
                "email": "testadmin@coopcore.ph",
                "password": "Admin@1234",
                "role": "super_admin",
                "branch": "Test Branch",
            },
            {
                "full_name": "Test Manager",
                "email": "testmanager@coopcore.ph",
                "password": "Manager@1234",
                "role": "branch_manager",
                "branch": "Test Branch",
            },
            {
                "full_name": "Test Cashier",
                "email": "testcashier@coopcore.ph",
                "password": "Cashier@1234",
                "role": "cashier",
                "branch": "Test Branch",
            },
        ]
        for u in users:
            if not service.get_by_email(u["email"]):
                service.create_user(u, created_by="test_setup")

    yield

    # Teardown — wipe the test DB collections used by auth/user tests
    with app.app_context():
        db.users.delete_many({"branch": "Test Branch"})
        db.audit_logs.delete_many({"details.email": {"$regex": "@coopcore.ph"}})


@pytest.fixture
def admin_token(client):
    """Returns a valid access token for the test super_admin."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "testadmin@coopcore.ph", "password": "Admin@1234"},
    )
    return resp.get_json()["access_token"]


@pytest.fixture
def manager_token(client):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "testmanager@coopcore.ph", "password": "Manager@1234"},
    )
    return resp.get_json()["access_token"]


@pytest.fixture
def cashier_token(client):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "testcashier@coopcore.ph", "password": "Cashier@1234"},
    )
    return resp.get_json()["access_token"]


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}