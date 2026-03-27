# backend/app/schemas/savings_schema.py
from marshmallow import Schema, fields, validate, validates, ValidationError, pre_load
from datetime import date

PRODUCT_TYPES = ["Regular Savings", "Time Deposit", "Special Savings"]
ACCOUNT_STATUSES = ["Active", "Dormant", "Closed"]
TRANSACTION_TYPES = ["Deposit", "Withdrawal", "Interest", "Fee", "Adjustment"]
PAYMENT_METHODS = ["Cash", "Bank Transfer", "Auto-debit", "Check"]


class OpenAccountSchema(Schema):
    """Used by branch_manager to open a new savings account for a member."""
    member_id = fields.Str(required=True)
    product_type = fields.Str(
        required=True,
        validate=validate.OneOf(PRODUCT_TYPES),
    )
    initial_deposit = fields.Float(
        load_default=0.0,
        validate=validate.Range(min=0, error="Initial deposit cannot be negative"),
    )
    passbook_number = fields.Str(load_default=None, allow_none=True,
                                  validate=validate.Length(max=20))
    # Time Deposit specific — required when product_type == "Time Deposit"
    term_months = fields.Int(load_default=None, allow_none=True,
                              validate=validate.Range(min=1, max=60))
    placement_amount = fields.Float(load_default=None, allow_none=True,
                                     validate=validate.Range(min=1))

    @pre_load
    def strip_strings(self, data: dict, **kwargs) -> dict:
        return {k: v.strip() if isinstance(v, str) else v for k, v in data.items()}

    def validate_time_deposit_fields(self, data: dict) -> None:
        if data.get("product_type") == "Time Deposit":
            if not data.get("term_months"):
                raise ValidationError(
                    {"term_months": ["term_months is required for Time Deposit accounts"]}
                )
            if not data.get("placement_amount"):
                raise ValidationError(
                    {"placement_amount": ["placement_amount is required for Time Deposit accounts"]}
                )

    def _do_load(self, data, *, partial, unknown, **kwargs):
        result = super()._do_load(data, partial=partial, unknown=unknown, **kwargs)
        self.validate_time_deposit_fields(result)
        return result


class TransactionSchema(Schema):
    """Used by cashier to post a deposit or withdrawal."""
    transaction_type = fields.Str(
        required=True,
        validate=validate.OneOf(
            ["Deposit", "Withdrawal"],
            error="Only Deposit or Withdrawal can be posted via this endpoint",
        ),
    )
    amount = fields.Float(
        required=True,
        validate=validate.Range(min=0.01, error="Amount must be greater than zero"),
    )
    payment_method = fields.Str(
        required=True,
        validate=validate.OneOf(PAYMENT_METHODS),
    )
    or_number = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50, error="OR number is required"),
    )
    reference_number = fields.Str(load_default=None, allow_none=True,
                                   validate=validate.Length(max=50))
    transaction_date = fields.Date(load_default=None, allow_none=True)
    remarks = fields.Str(load_default="", validate=validate.Length(max=300))

    @pre_load
    def strip_strings(self, data: dict, **kwargs) -> dict:
        return {k: v.strip() if isinstance(v, str) else v for k, v in data.items()}


class PostInterestSchema(Schema):
    """
    Used by branch_manager to trigger monthly interest posting.
    Can target a single account_id or all active accounts for a product type.
    """
    account_id = fields.Str(load_default=None, allow_none=True)
    product_type = fields.Str(
        load_default=None,
        allow_none=True,
        validate=validate.OneOf(PRODUCT_TYPES),
    )
    as_of_date = fields.Date(load_default=None, allow_none=True)

    @pre_load
    def strip_strings(self, data: dict, **kwargs) -> dict:
        return {k: v.strip() if isinstance(v, str) else v for k, v in data.items()}


class UpdateAccountSchema(Schema):
    """Used by branch_manager to update non-financial account metadata."""
    status = fields.Str(validate=validate.OneOf(ACCOUNT_STATUSES))
    passbook_number = fields.Str(allow_none=True, validate=validate.Length(max=20))
    interest_rate = fields.Float(validate=validate.Range(min=0, max=100))

    @pre_load
    def strip_strings(self, data: dict, **kwargs) -> dict:
        return {k: v.strip() if isinstance(v, str) else v for k, v in data.items()}