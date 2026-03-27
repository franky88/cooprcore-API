# backend/app/schemas/loan_schema.py
from marshmallow import Schema, fields, validate, validates, ValidationError, pre_load
from .member_schema import _validate_ph_phone
from ..utils.loan_calculator import LOAN_TYPES, LOAN_TYPE_CONFIG

PAYMENT_METHODS = ["Cash", "Bank Transfer", "Auto-debit"]


class CoMakerSchema(Schema):
    member_id = fields.Str(required=True)
    name = fields.Str(required=True, validate=validate.Length(min=2, max=100))


class CollateralSchema(Schema):
    type = fields.Str(required=True, validate=validate.Length(min=2, max=50))
    description = fields.Str(required=True, validate=validate.Length(min=2, max=200))
    value = fields.Float(required=True, validate=validate.Range(min=1))


class LoanApplicationSchema(Schema):
    """Used when a loan officer submits a new loan application."""
    member_id = fields.Str(required=True)
    loan_type = fields.Str(
        required=True,
        validate=validate.OneOf(LOAN_TYPES, error="Invalid loan type"),
    )
    principal = fields.Float(
        required=True,
        validate=validate.Range(min=1000, error="Minimum loan amount is ₱1,000"),
    )
    term_months = fields.Int(
        required=True,
        validate=validate.Range(min=1, error="Term must be at least 1 month"),
    )
    purpose = fields.Str(
        required=True,
        validate=validate.Length(min=5, max=300, error="Purpose must be between 5 and 300 characters"),
    )
    co_makers = fields.List(fields.Nested(CoMakerSchema), load_default=[])
    collateral = fields.Nested(CollateralSchema, load_default=None, allow_none=True)

    @pre_load
    def strip_strings(self, data: dict, **kwargs) -> dict:
        return {k: v.strip() if isinstance(v, str) else v for k, v in data.items()}

    @validates("term_months")
    def validate_term(self, value: int) -> None:
        # We don't know loan_type here yet, so max_term is enforced in the service
        if value > 60:
            raise ValidationError("Term cannot exceed 60 months")


class ApprovalSchema(Schema):
    """Used by branch_manager when approving a loan."""
    notes = fields.Str(load_default="", validate=validate.Length(max=500))


class RejectionSchema(Schema):
    """Used by branch_manager when rejecting a loan."""
    reason = fields.Str(
        required=True,
        validate=validate.Length(min=5, max=500, error="Reason must be between 5 and 500 characters"),
    )


class PostPaymentSchema(Schema):
    """Used by cashier to record a loan repayment."""
    amount_paid = fields.Float(
        required=True,
        validate=validate.Range(min=0.01, error="Payment amount must be greater than zero"),
    )
    payment_method = fields.Str(
        required=True,
        validate=validate.OneOf(PAYMENT_METHODS),
    )
    or_number = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50, error="OR number is required"),
    )
    payment_date = fields.Date(load_default=None, allow_none=True)
    remarks = fields.Str(load_default="", validate=validate.Length(max=300))

    @pre_load
    def strip_strings(self, data: dict, **kwargs) -> dict:
        return {k: v.strip() if isinstance(v, str) else v for k, v in data.items()}


class ReleaseSchema(Schema):
    """Used by cashier/manager when disbursing loan funds."""
    or_number = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
    )
    release_date = fields.Date(load_default=None, allow_none=True)
    remarks = fields.Str(load_default="", validate=validate.Length(max=300))

    @pre_load
    def strip_strings(self, data: dict, **kwargs) -> dict:
        return {k: v.strip() if isinstance(v, str) else v for k, v in data.items()}