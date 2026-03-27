# backend/scripts/seed.py
"""
Run from the backend/ directory:
    python scripts/seed.py

Creates one user per role so the system is usable immediately after setup.
Safe to run multiple times — skips existing emails.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.services.user_service import UserService

SEED_USERS = [
    {
        "full_name": "System Administrator",
        "email": "admin@coopcore.ph",
        "password": "Admin@1234",
        "role": "super_admin",
        "branch": "Head Office",
    },
    {
        "full_name": "Branch Manager",
        "email": "manager@coopcore.ph",
        "password": "Manager@1234",
        "role": "branch_manager",
        "branch": "Main Branch",
    },
    {
        "full_name": "Loan Officer",
        "email": "loanofficer@coopcore.ph",
        "password": "Officer@1234",
        "role": "loan_officer",
        "branch": "Main Branch",
    },
    {
        "full_name": "Cashier",
        "email": "cashier@coopcore.ph",
        "password": "Cashier@1234",
        "role": "cashier",
        "branch": "Main Branch",
    },
]


def run():
    app = create_app("development")
    service = UserService()

    with app.app_context():
        print("Seeding users...\n")
        for u in SEED_USERS:
            existing = service.get_by_email(u["email"])
            if existing:
                print(f"  SKIP  {u['email']} (already exists)")
                continue
            result = service.create_user(u, created_by="seed_script")
            if "error" in result:
                print(f"  ERROR {u['email']}: {result['error']}")
            else:
                print(f"  OK    {u['email']}  →  {result['employee_id']}  [{u['role']}]")

    print("\nDone. Default passwords are in scripts/seed.py — change them after first login.")


if __name__ == "__main__":
    run()