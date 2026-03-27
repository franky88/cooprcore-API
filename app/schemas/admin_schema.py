# backend/app/schemas/admin_schema.py
from marshmallow import Schema, fields, validate, pre_load

class LoanTypeRateSchema(Schema):
    rate = fields.Float(
        required=True,
        validate=validate.Range(min=0.01, max=100)
    )
    max_term = fields.Int(
        required=True,
        validate=validate.Range(min=1, max=120)
    )

class UpdateSettingsSchema(Schema):
    """
    All fields are optional — only provided fields are updated.
    Unknown fields are ignored by Marshmallow (Meta.unknown = EXCLUDE).
    """

    coop_name = fields.Str(validate=validate.Length(min=2, max=150))
    address = fields.Str(validate=validate.Length(max=300))
    contact_email = fields.Email(allow_none=True)
    contact_phone = fields.Str(
        allow_none=True,
        validate=validate.Length(max=20),
    )

    # Financial rates
    default_loan_rate = fields.Float(
        validate=validate.Range(min=0.01, max=100, error="Loan rate must be between 0.01% and 100%")
    )
    default_savings_rate = fields.Float(
        validate=validate.Range(min=0, max=100, error="Savings rate must be between 0% and 100%")
    )
    share_par_value = fields.Float(
        validate=validate.Range(min=1, error="Share par value must be at least ₱1")
    )
    withholding_tax_rate = fields.Float(
        validate=validate.Range(min=0, max=100, error="Withholding tax rate must be between 0% and 100%")
    )
    penalty_rate_monthly = fields.Float(
        validate=validate.Range(min=0, max=100, error="Penalty rate must be between 0% and 100%")
    )

    # Business rule thresholds
    comaker_threshold = fields.Float(
        validate=validate.Range(min=1, error="Co-maker threshold must be greater than zero")
    )
    max_active_loans = fields.Int(
        validate=validate.Range(min=1, max=10, error="Max active loans must be between 1 and 10")
    )
    dormancy_months = fields.Int(
        validate=validate.Range(min=1, max=60, error="Dormancy period must be between 1 and 60 months")
    )
    fiscal_year_start_month = fields.Int(
        validate=validate.Range(min=1, max=12, error="Fiscal year start month must be between 1 and 12")
    )
    # ── Per-type loan rates ──────────────────────────────────────────
    loan_rates = fields.Dict(
        keys=fields.Str(),
        values=fields.Nested(LoanTypeRateSchema),
        load_default=None,
        allow_none=True,
    )

    @pre_load
    def strip_strings(self, data: dict, **kwargs) -> dict:
        return {
            k: v.strip() if isinstance(v, str) else v
            for k, v in data.items()
        }

    class Meta:
        # Silently drop any fields not defined above
        unknown = __import__("marshmallow").EXCLUDE


class AuditLogFilterSchema(Schema):
    """
    Validates query parameters for GET /admin/audit-logs.
    All fields are optional.
    """
    page = fields.Int(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Int(load_default=50, validate=validate.Range(min=1, max=200))
    actor_id = fields.Str(load_default=None, allow_none=True)
    resource = fields.Str(load_default=None, allow_none=True)
    action = fields.Str(load_default=None, allow_none=True)
    date_from = fields.Str(load_default=None, allow_none=True)
    date_to = fields.Str(load_default=None, allow_none=True)