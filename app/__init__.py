import os
from flask import Flask, jsonify
from .config import config_by_env
from .extensions import jwt, cors, mongo


def create_app(env: str | None = None) -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    env = env or os.getenv("FLASK_ENV", "development")
    app.config.from_object(config_by_env[env])

    # ------------------------------------------------------------------ #
    # Extensions
    # ------------------------------------------------------------------ #
    mongo.init_app(app)
    jwt.init_app(app)
    cors.init_app(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})

    # ------------------------------------------------------------------ #
    # Ensure MongoDB indexes on first startup
    # ------------------------------------------------------------------ #
    with app.app_context():
        _ensure_indexes()

    # ------------------------------------------------------------------ #
    # Blueprints
    # ------------------------------------------------------------------ #
    api = "/api/v1"
    from .blueprints.auth import auth_bp
    from .blueprints.users import users_bp
    from .blueprints.members import members_bp
    from .blueprints.loans import loans_bp
    from .blueprints.savings import savings_bp
    from .blueprints.shares import shares_bp
    from .blueprints.admin import admin_bp
    from .blueprints.member_portal import member_portal_bp
    from .blueprints.member_auth import member_auth_bp

    app.register_blueprint(auth_bp, url_prefix=f"{api}/auth")
    app.register_blueprint(users_bp, url_prefix=f"{api}/users")
    app.register_blueprint(members_bp, url_prefix=f"{api}/members")
    app.register_blueprint(loans_bp, url_prefix=f"{api}/loans")
    app.register_blueprint(savings_bp, url_prefix=f"{api}/savings")
    app.register_blueprint(shares_bp, url_prefix=f"{api}/shares")
    app.register_blueprint(admin_bp, url_prefix=f"{api}/admin")
    app.register_blueprint(member_portal_bp, url_prefix=f"{api}/member-portal")
    app.register_blueprint(member_auth_bp, url_prefix=f"{api}/member-auth")

    # ------------------------------------------------------------------ #
    # Scheduler (background jobs)
    # ------------------------------------------------------------------ #
    from .scheduler import init_scheduler
    init_scheduler(app)

    # ------------------------------------------------------------------ #
    # JWT error handlers — return JSON instead of default HTML
    # ------------------------------------------------------------------ #
    @jwt.unauthorized_loader
    def missing_token(_reason: str):
        return jsonify({"error": "Authorization token is missing"}), 401

    @jwt.invalid_token_loader
    def invalid_token(_reason: str):
        return jsonify({"error": "Authorization token is invalid"}), 401

    @jwt.expired_token_loader
    def expired_token(_jwt_header, _jwt_data):
        return jsonify({"error": "Token has expired"}), 401

    @jwt.revoked_token_loader
    def revoked_token(_jwt_header, _jwt_data):
        return jsonify({"error": "Token has been revoked"}), 401

    # ------------------------------------------------------------------ #
    # Generic 404 / 405
    # ------------------------------------------------------------------ #
    @app.errorhandler(404)
    def not_found(_e):
        return jsonify({"error": "Resource not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(_e):
        return jsonify({"error": "Method not allowed"}), 405

    return app


def _ensure_indexes() -> None:
    """Create all MongoDB indexes at startup (idempotent)."""
    from .extensions import mongo as m
    db = m.db

    # users
    db.users.create_index("email", unique=True)
    db.users.create_index("employee_id", unique=True)
    db.users.create_index("role")
    db.users.create_index("is_active")

    # members
    db.members.create_index("member_id", unique=True)
    db.members.create_index("email", unique=True, sparse=True)
    db.members.create_index("phone", unique=True)
    db.members.create_index("status")
    db.members.create_index("membership_type")
    db.members.create_index([("last_name", 1), ("first_name", 1)])

    # loans
    db.loans.create_index("loan_id", unique=True)
    db.loans.create_index("member_id")
    db.loans.create_index("status")
    db.loans.create_index("date_applied")
    db.loans.create_index([("status", 1), ("maturity_date", 1)])

    # loan_payments
    db.loan_payments.create_index("payment_id", unique=True)
    db.loan_payments.create_index("loan_id")
    db.loan_payments.create_index("member_id")
    db.loan_payments.create_index("payment_date")

    # savings_accounts
    db.savings_accounts.create_index("account_id", unique=True)
    db.savings_accounts.create_index("member_id")
    db.savings_accounts.create_index("status")

    # savings_transactions
    db.savings_transactions.create_index("transaction_id", unique=True)
    db.savings_transactions.create_index("account_id")
    db.savings_transactions.create_index("member_id")
    db.savings_transactions.create_index("transaction_date")

    # share_capital
    db.share_capital.create_index("share_id", unique=True)
    db.share_capital.create_index("member_id", unique=True)

    # share_payments
    db.share_payments.create_index("payment_id", unique=True)
    db.share_payments.create_index("share_id")
    db.share_payments.create_index("member_id")
    db.share_payments.create_index([("fiscal_year", 1), ("payment_type", 1)])

    # settings — singleton document
    db.settings.create_index("key", unique=True)

    # audit_logs — TTL: keep 2 years (63072000 seconds)
    db.audit_logs.create_index("created_at", expireAfterSeconds=63072000)
    db.audit_logs.create_index("actor_id")
    db.audit_logs.create_index([("resource", 1), ("resource_id", 1)])

    # counters — atomic ID sequences
    # db.counters.create_index("_id", unique=True)