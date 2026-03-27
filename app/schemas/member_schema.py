# backend/app/schemas/member_schema.py
from marshmallow import (
    Schema,
    fields,
    validate,
    validates,
    validates_schema,
    ValidationError,
    pre_load,
)
import re
from datetime import date

# ------------------------------------------------------------------ #
# Constants
# ------------------------------------------------------------------ #

MEMBERSHIP_TYPES = ["Regular", "Associate"]
MEMBER_STATUSES = ["Active", "Inactive", "Suspended", "Deceased"]
GENDERS = ["Male", "Female"]
CIVIL_STATUSES = ["Single", "Married", "Widowed", "Separated", "Annulled"]
ID_TYPES = ["SSS", "GSIS", "PhilHealth", "Pag-IBIG", "TIN", "Passport", "Driver's License", "Voter's ID", "PRC ID", "National ID"]


# ------------------------------------------------------------------ #
# Nested Schemas
# ------------------------------------------------------------------ #

class AddressSchema(Schema):
    street = fields.Str(required=True, validate=validate.Length(min=2, max=200))
    barangay = fields.Str(required=True, validate=validate.Length(min=2, max=100))
    city = fields.Str(required=True, validate=validate.Length(min=2, max=100))
    province = fields.Str(required=True, validate=validate.Length(min=2, max=100))
    zip_code = fields.Str(required=True, validate=validate.Regexp(r"^\d{4}$", error="Zip code must be 4 digits"))


class NomineeSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=2, max=100))
    relationship = fields.Str(required=True, validate=validate.Length(min=2, max=50))
    phone = fields.Str(required=True)

    @validates("phone")
    def validate_phone(self, value: str) -> None:
        _validate_ph_phone(value)


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _validate_ph_phone(value: str) -> None:
    """Accepts 09XXXXXXXXX or +639XXXXXXXXX formats."""
    if not re.match(r"^(09\d{9}|\+639\d{9})$", value):
        raise ValidationError(
            "Phone must be in 09XXXXXXXXX or +639XXXXXXXXX format"
        )


def _validate_tin(value: str) -> None:
    if not re.match(r"^\d{3}-\d{3}-\d{3}-\d{3}$", value):
        raise ValidationError("TIN must be in NNN-NNN-NNN-NNN format")


# ------------------------------------------------------------------ #
# Create / Register Schema
# ------------------------------------------------------------------ #

class CreateMemberSchema(Schema):
    # Membership
    membership_type = fields.Str(
        load_default="Regular",
        validate=validate.OneOf(MEMBERSHIP_TYPES),
    )

    # Personal
    first_name = fields.Str(required=True, validate=validate.Length(min=1, max=50))
    middle_name = fields.Str(load_default="", validate=validate.Length(max=50))
    last_name = fields.Str(required=True, validate=validate.Length(min=1, max=50))
    suffix = fields.Str(load_default="", validate=validate.Length(max=10))
    date_of_birth = fields.Date(required=True)
    gender = fields.Str(required=True, validate=validate.OneOf(GENDERS))
    civil_status = fields.Str(required=True, validate=validate.OneOf(CIVIL_STATUSES))
    nationality = fields.Str(load_default="Filipino", validate=validate.Length(max=50))
    tin = fields.Str(load_default=None, allow_none=True)

    # Contact
    email = fields.Email(load_default=None, allow_none=True)
    phone = fields.Str(required=True)
    address = fields.Nested(AddressSchema, required=True)

    # Employment
    employer = fields.Str(load_default="", validate=validate.Length(max=150))
    occupation = fields.Str(load_default="", validate=validate.Length(max=100))
    monthly_income = fields.Float(
        load_default=0.0,
        validate=validate.Range(min=0, error="Monthly income cannot be negative"),
    )

    # Cooperative
    nominee = fields.Nested(NomineeSchema, required=True)

    # ID
    id_type = fields.Str(
        required=True,
        validate=validate.OneOf(ID_TYPES),
    )
    id_number = fields.Str(required=True, validate=validate.Length(min=3, max=30))

    @pre_load
    def strip_strings(self, data: dict, **kwargs) -> dict:
        return {
            k: v.strip() if isinstance(v, str) else v
            for k, v in data.items()
        }

    @validates("phone")
    def validate_phone(self, value: str) -> None:
        _validate_ph_phone(value)

    @validates("tin")
    def validate_tin(self, value: str | None) -> None:
        if value:
            _validate_tin(value)

    @validates("date_of_birth")
    def validate_dob(self, value: date) -> None:
        today = date.today()
        age = (today - value).days // 365
        if age < 18:
            raise ValidationError("Member must be at least 18 years old")
        if age > 100:
            raise ValidationError("Date of birth appears invalid")


# ------------------------------------------------------------------ #
# Update Schema — all fields optional
# ------------------------------------------------------------------ #

class UpdateMemberSchema(Schema):
    first_name = fields.Str(validate=validate.Length(min=1, max=50))
    middle_name = fields.Str(validate=validate.Length(max=50))
    last_name = fields.Str(validate=validate.Length(min=1, max=50))
    suffix = fields.Str(validate=validate.Length(max=10))
    gender = fields.Str(validate=validate.OneOf(GENDERS))
    civil_status = fields.Str(validate=validate.OneOf(CIVIL_STATUSES))
    nationality = fields.Str(validate=validate.Length(max=50))
    tin = fields.Str(allow_none=True)
    email = fields.Email(allow_none=True)
    phone = fields.Str()
    address = fields.Nested(AddressSchema)
    employer = fields.Str(validate=validate.Length(max=150))
    occupation = fields.Str(validate=validate.Length(max=100))
    monthly_income = fields.Float(validate=validate.Range(min=0))
    nominee = fields.Nested(NomineeSchema)
    id_type = fields.Str(validate=validate.OneOf(ID_TYPES))
    id_number = fields.Str(validate=validate.Length(min=3, max=30))
    status = fields.Str(validate=validate.OneOf(MEMBER_STATUSES))
    membership_type = fields.Str(validate=validate.OneOf(MEMBERSHIP_TYPES))
    photo_url = fields.Str(allow_none=True)
    signature_url = fields.Str(allow_none=True)

    @pre_load
    def strip_strings(self, data: dict, **kwargs) -> dict:
        return {
            k: v.strip() if isinstance(v, str) else v
            for k, v in data.items()
        }

    @validates("phone")
    def validate_phone(self, value: str) -> None:
        _validate_ph_phone(value)

    @validates("tin")
    def validate_tin(self, value: str | None) -> None:
        if value:
            _validate_tin(value)