from marshmallow import Schema, fields, validate, validates_schema, ValidationError, pre_load


class MemberActivationStartSchema(Schema):
    member_id = fields.Str(required=True, validate=validate.Length(min=1, max=50))
    email = fields.Email(required=True)
    date_of_birth = fields.Date(required=True)

    @pre_load
    def strip_strings(self, data, **kwargs):
        return {
            k: v.strip() if isinstance(v, str) else v
            for k, v in data.items()
        }


class MemberActivationCompleteSchema(Schema):
    member_id = fields.Str(required=True, validate=validate.Length(min=1, max=50))
    otp = fields.Str(required=True, validate=validate.Regexp(r"^\d{6}$"))
    password = fields.Str(required=True, validate=validate.Length(min=8, max=128))
    confirm_password = fields.Str(required=True, validate=validate.Length(min=8, max=128))

    @pre_load
    def strip_strings(self, data, **kwargs):
        return {
            k: v.strip() if isinstance(v, str) else v
            for k, v in data.items()
        }

    @validates_schema
    def validate_passwords(self, data, **kwargs):
        if data["password"] != data["confirm_password"]:
            raise ValidationError(
                {"confirm_password": ["Passwords do not match."]}
            )