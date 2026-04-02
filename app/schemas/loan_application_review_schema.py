from marshmallow import Schema, fields, validate, validates_schema, ValidationError, pre_load


class LoanApplicationReviewSchema(Schema):
    remarks = fields.Str(
        required=False,
        load_default="",
        validate=validate.Length(max=300),
    )

    @pre_load
    def strip_strings(self, data: dict, **kwargs) -> dict:
        return {
            k: v.strip() if isinstance(v, str) else v
            for k, v in (data or {}).items()
        }


class LoanApplicationRejectSchema(Schema):
    rejected_reason = fields.Str(
        required=True,
        validate=validate.Length(min=5, max=300),
    )
    remarks = fields.Str(
        required=False,
        load_default="",
        validate=validate.Length(max=300),
    )

    @pre_load
    def strip_strings(self, data: dict, **kwargs) -> dict:
        return {
            k: v.strip() if isinstance(v, str) else v
            for k, v in (data or {}).items()
        }


class LoanApplicationApproveSchema(Schema):
    remarks = fields.Str(
        required=False,
        load_default="",
        validate=validate.Length(max=300),
    )