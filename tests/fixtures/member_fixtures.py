# backend/tests/fixtures/member_fixtures.py
"""
Shared member payload factories.
Import these into any test module that needs to create member data.
"""


def valid_member_payload(overrides: dict | None = None) -> dict:
    base = {
        "membership_type": "Regular",
        "first_name": "Juan",
        "middle_name": "Santos",
        "last_name": "Dela Cruz",
        "suffix": "",
        "date_of_birth": "1990-05-15",
        "gender": "Male",
        "civil_status": "Single",
        "nationality": "Filipino",
        "tin": "123-456-789-000",
        "email": "juan.delacruz@email.com",
        "phone": "09171234567",
        "address": {
            "street": "123 Rizal St.",
            "barangay": "Poblacion",
            "city": "Cebu City",
            "province": "Cebu",
            "zip_code": "6000",
        },
        "employer": "ABC Company",
        "occupation": "Engineer",
        "monthly_income": 35000,
        "nominee": {
            "name": "Maria Dela Cruz",
            "relationship": "Spouse",
            "phone": "09281234567",
        },
        "id_type": "SSS",
        "id_number": "12-3456789-0",
    }
    if overrides:
        base.update(overrides)
    return base