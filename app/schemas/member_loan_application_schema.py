from marshmallow import Schema, fields, validate, validates_schema, ValidationError, pre_load
from ..utils.loan_calculator import LOAN_TYPES, LOAN_TYPE_CONFIG


class MemberCoMakerSchema(Schema):
    member_id = fields.Str(required=True, validate=validate.Length(min=1, max=50))
    name = fields.Str(required=True, validate=validate.Length(min=2, max=120))


class MemberLoanApplicationCreateSchema(Schema):
    loan_type = fields.Str(
        required=True,
        validate=validate.OneOf(LOAN_TYPES, error="Invalid loan type"),
    )
    principal = fields.Float(
        required=True,
        validate=validate.Range(min=1, error="Principal must be greater than zero"),
    )
    term_months = fields.Int(
        required=True,
        validate=validate.Range(min=1, error="Term must be at least 1 month"),
    )
    purpose = fields.Str(
        required=True,
        validate=validate.Length(min=5, max=300),
    )
    co_makers = fields.List(
        fields.Nested(MemberCoMakerSchema),
        required=False,
        load_default=list,
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

    @validates_schema
    def validate_business_rules(self, data: dict, **kwargs) -> None:
        loan_type = data.get("loan_type")
        principal = data.get("principal")
        term_months = data.get("term_months")
        co_makers = data.get("co_makers", [])

        if loan_type in LOAN_TYPE_CONFIG:
            config = LOAN_TYPE_CONFIG[loan_type]
            max_term = int(config.get("max_term_months", 0) or 0)
            if max_term and term_months and term_months > max_term:
                raise ValidationError(
                    {"term_months": [f"Maximum term for {loan_type} is {max_term} months."]}
                )

        if principal and principal > 30000 and not co_makers:
            raise ValidationError(
                {"co_makers": ["Co-maker is required for loan amounts above ₱30,000."]}
            )