# backend/app/schemas/share_schema.py
from marshmallow import Schema, fields, validate, validates, ValidationError, pre_load

PAR_VALUE = 100.0  # ₱ per share — matches SHARE_PAR_VALUE in config


class UpdateSubscriptionSchema(Schema):
    """
    Used by loan_officer / manager to update a member's share subscription.
    Represents the member committing to buy more shares — no money changes
    hands here, only the subscribed_shares count is updated.
    """
    additional_shares = fields.Int(
        required=True,
        validate=validate.Range(
            min=1, error="Must subscribe at least 1 additional share"
        ),
    )
    remarks = fields.Str(load_default="", validate=validate.Length(max=300))

    @pre_load
    def strip_strings(self, data: dict, **kwargs) -> dict:
        return {k: v.strip() if isinstance(v, str) else v for k, v in data.items()}


class RecordPaymentSchema(Schema):
    """
    Used by cashier to record a share capital payment.
    Payment is in peso amounts; shares_paid is derived from amount / par_value.
    """
    amount_paid = fields.Float(
        required=True,
        validate=validate.Range(
            min=100.0,
            error=f"Minimum payment is ₱{PAR_VALUE:.0f} (1 share at par value)",
        ),
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

    @validates("amount_paid")
    def validate_multiple_of_par(self, value: float) -> None:
        """Payment must be an exact multiple of the par value (₱100)."""
        if round(value % PAR_VALUE, 2) != 0:
            raise ValidationError(
                f"Amount must be a multiple of ₱{PAR_VALUE:.0f} (par value per share). "
                f"e.g. ₱100, ₱500, ₱1,000"
            )


class DividendSchema(Schema):
    """
    Used by super_admin / branch_manager to declare and distribute dividends.
    dividend_rate: percentage of paid-up amount to distribute (e.g. 10 = 10%)
    fiscal_year: the year the dividend covers
    """
    dividend_rate = fields.Float(
        required=True,
        validate=validate.Range(
            min=0.01, max=100,
            error="Dividend rate must be between 0.01% and 100%",
        ),
    )
    fiscal_year = fields.Int(
        required=True,
        validate=validate.Range(
            min=2000, max=2100,
            error="Invalid fiscal year",
        ),
    )
    remarks = fields.Str(load_default="", validate=validate.Length(max=300))

    @pre_load
    def strip_strings(self, data: dict, **kwargs) -> dict:
        return {k: v.strip() if isinstance(v, str) else v for k, v in data.items()}