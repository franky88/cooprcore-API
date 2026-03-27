# backend/app/schemas/user_schema.py
from marshmallow import Schema, fields, validate, validates, ValidationError, pre_load

ROLES = ["super_admin", "branch_manager", "loan_officer", "cashier"]


class CreateUserSchema(Schema):
    full_name = fields.Str(required=True, validate=validate.Length(min=2, max=100))
    email = fields.Email(required=True)
    password = fields.Str(required=True, load_only=True, validate=validate.Length(min=8))
    role = fields.Str(
        required=True,
        validate=validate.OneOf(ROLES, error="Invalid role"),
    )
    branch = fields.Str(load_default="Main Branch", validate=validate.Length(max=100))

    @pre_load
    def strip_strings(self, data: dict, **kwargs) -> dict:
        return {
            k: v.strip() if isinstance(v, str) else v
            for k, v in data.items()
        }

    @validates("password")
    def validate_password(self, value: str) -> None:
        from ..utils.validators import validate_password_strength
        errors = validate_password_strength(value)
        if errors:
            raise ValidationError(errors)


class UpdateUserSchema(Schema):
    full_name = fields.Str(validate=validate.Length(min=2, max=100))
    role = fields.Str(validate=validate.OneOf(ROLES))
    branch = fields.Str(validate=validate.Length(max=100))
    is_active = fields.Bool()

    @pre_load
    def strip_strings(self, data: dict, **kwargs) -> dict:
        return {
            k: v.strip() if isinstance(v, str) else v
            for k, v in data.items()
        }


class ChangePasswordSchema(Schema):
    current_password = fields.Str(required=True, load_only=True)
    new_password = fields.Str(required=True, load_only=True, validate=validate.Length(min=8))

    @validates("new_password")
    def validate_new_password(self, value: str) -> None:
        from ..utils.validators import validate_password_strength
        errors = validate_password_strength(value)
        if errors:
            raise ValidationError(errors)


class UserResponseSchema(Schema):
    """Output schema — never exposes password_hash."""
    id = fields.Str(dump_default="")
    employee_id = fields.Str()
    full_name = fields.Str()
    email = fields.Email()
    role = fields.Str()
    branch = fields.Str()
    is_active = fields.Bool()
    created_at = fields.DateTime(format="iso")
    updated_at = fields.DateTime(format="iso")
    last_login = fields.DateTime(format="iso", allow_none=True)