# backend/app/blueprints/admin.py
from bson import ObjectId
from datetime import datetime
import bcrypt
from ..extensions import mongo
import math
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from ..services.admin_service import AdminService
from ..middleware.auth_middleware import roles_required

admin_bp = Blueprint("admin", __name__)
service = AdminService()

_MANAGER_AND_ABOVE = ("super_admin", "branch_manager")


# ------------------------------------------------------------------ #
# Dashboard
# ------------------------------------------------------------------ #

@admin_bp.get("/dashboard")
@jwt_required()
@roles_required(*_MANAGER_AND_ABOVE)
def dashboard():
    """
    GET /api/v1/admin/dashboard
    Top-level KPIs: member counts, loan portfolio, savings total,
    share capital paid-up. Used by the dashboard home page.
    """
    return jsonify(service.dashboard_summary()), 200


# ------------------------------------------------------------------ #
# Settings
# ------------------------------------------------------------------ #

@admin_bp.get("/settings")
@jwt_required()
@roles_required("super_admin")
def get_settings():
    """GET /api/v1/admin/settings"""
    return jsonify(service.get_settings()), 200


@admin_bp.put("/settings")
@jwt_required()
@roles_required("super_admin")
def update_settings():
    """
    PUT /api/v1/admin/settings
    Accepts any subset of the settings fields.
    Unknown fields are silently ignored.
    """
    data = request.get_json(silent=True) or {}
    updated_by = get_jwt_identity()

    result = service.update_settings(data, updated_by=updated_by)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 200


# ------------------------------------------------------------------ #
# Audit logs
# ------------------------------------------------------------------ #

@admin_bp.get("/audit-logs")
@jwt_required()
@roles_required("super_admin")
def audit_logs():
    """
    GET /api/v1/admin/audit-logs
    Query params:
      page, per_page
      actor_id    — filter by the JWT identity (user ObjectId) who performed the action
      resource    — e.g. "members", "loans", "savings_accounts"
      action      — partial match, e.g. "LOAN" matches APPROVE_LOAN, RELEASE_LOAN, etc.
      date_from   — ISO date string  e.g. 2024-01-01
      date_to     — ISO date string  e.g. 2024-12-31
    """
    result = service.get_audit_logs(
        page=int(request.args.get("page", 1)),
        per_page=int(request.args.get("per_page", 50)),
        actor_id=request.args.get("actor_id"),
        resource=request.args.get("resource"),
        action=request.args.get("action"),
        date_from=request.args.get("date_from"),
        date_to=request.args.get("date_to"),
    )
    return jsonify(result), 200


# ------------------------------------------------------------------ #
# Reports
# ------------------------------------------------------------------ #

@admin_bp.post("/past-due-check")
@jwt_required()
@roles_required(*_MANAGER_AND_ABOVE)
def run_past_due_check():
    """
    POST /api/v1/admin/past-due-check
    Manually triggers the past-due automation job.
    Normally runs automatically at 01:00 AM daily.
    Returns a summary of how many loans were marked Past Due.
    """
    from ..services.loan_service import LoanService
    result = LoanService().mark_past_due()
    return jsonify(result), 200
 
 
@admin_bp.post("/dormancy-check")
@jwt_required()
@roles_required(*_MANAGER_AND_ABOVE)
def run_dormancy_check():
    """
    POST /api/v1/admin/dormancy-check
    Manually triggers the savings dormancy check.
    Normally runs automatically on the 1st of every month at 02:00 AM.
    """
    from ..services.savings_service import SavingsService
    result = SavingsService().mark_dormant_accounts()
    return jsonify(result), 200
 
 
@admin_bp.get("/scheduler/status")
@jwt_required()
@roles_required("super_admin")
def scheduler_status():
    """
    GET /api/v1/admin/scheduler/status
    Returns the current state of all scheduled jobs.
    """
    from ..scheduler import get_scheduler
    scheduler = get_scheduler()
 
    if not scheduler or not scheduler.running:
        return jsonify({"running": False, "jobs": []}), 200
 
    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": next_run.isoformat() if next_run else None,
        })
 
    return jsonify({"running": True, "jobs": jobs}), 200

@admin_bp.get("/reports/members")
@jwt_required()
@roles_required(*_MANAGER_AND_ABOVE)
def report_members():
    """
    GET /api/v1/admin/reports/members
    Query params: status, membership_type
    Returns full member listing with status aggregate counts.
    """
    result = service.report_members(
        status=request.args.get("status"),
        membership_type=request.args.get("membership_type"),
    )
    return jsonify(result), 200


@admin_bp.get("/reports/loans")
@jwt_required()
@roles_required(*_MANAGER_AND_ABOVE)
def report_loans():
    """
    GET /api/v1/admin/reports/loans
    Query params: status
    Returns loan portfolio with aging data and summary by status.
    """
    result = service.report_loans(
        status=request.args.get("status"),
    )
    return jsonify(result), 200


@admin_bp.get("/reports/savings")
@jwt_required()
@roles_required(*_MANAGER_AND_ABOVE)
def report_savings():
    """
    GET /api/v1/admin/reports/savings
    Query params: product_type
    Returns savings portfolio summary by product type.
    """
    result = service.report_savings(
        product_type=request.args.get("product_type"),
    )
    return jsonify(result), 200


@admin_bp.get("/reports/shares")
@jwt_required()
@roles_required(*_MANAGER_AND_ABOVE)
def report_shares():
    """
    GET /api/v1/admin/reports/shares
    Returns share capital portfolio with aggregate totals.
    """
    return jsonify(service.report_shares()), 200

# ------------------------------------------------------------------ #
# Users
# ------------------------------------------------------------------ #

@admin_bp.get("/users")
@jwt_required()
@roles_required("super_admin")
def list_users():
    """GET /api/v1/admin/users?page=1&per_page=20&search=&role="""
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    search = request.args.get("search")
    role = request.args.get("role")

    query = {}
    if role:
        query["role"] = role
    if search:
        query["$or"] = [
            {"full_name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"employee_id": {"$regex": search, "$options": "i"}},
        ]

    total = mongo.db.users.count_documents(query)
    users = list(
        mongo.db.users
        .find(query, {"password_hash": 0})
        .sort("full_name", 1)
        .skip((page - 1) * per_page)
        .limit(per_page)
    )

    for u in users:
        u["id"] = str(u.pop("_id"))
        for field in ("created_at", "updated_at", "last_login"):
            val = u.get(field)
            if isinstance(val, datetime):
                u[field] = val.isoformat()

    return jsonify({
        "data": users,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": math.ceil(total / per_page) if total else 0,
        },
    }), 200


@admin_bp.post("/users")
@jwt_required()
@roles_required("super_admin")
def create_user():
    """POST /api/v1/admin/users"""
    data = request.get_json(silent=True) or {}

    required = ["employee_id", "full_name", "email", "password", "role", "branch"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"{field} is required"}), 400

    if mongo.db.users.find_one({"email": data["email"]}):
        return jsonify({"error": "Email already registered"}), 400

    if mongo.db.users.find_one({"employee_id": data["employee_id"]}):
        return jsonify({"error": "Employee ID already exists"}), 400

    valid_roles = [
        "super_admin", "branch_manager",
        "loan_officer", "cashier", "member",
    ]
    if data["role"] not in valid_roles:
        return jsonify({"error": f"Invalid role. Must be one of: {valid_roles}"}), 400

    now = datetime.utcnow()
    password_hash = bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt())

    result = mongo.db.users.insert_one({
        "employee_id": data["employee_id"],
        "full_name": data["full_name"],
        "email": data["email"],
        "password_hash": password_hash,
        "role": data["role"],
        "branch": data["branch"],
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "last_login": None,
    })

    created = mongo.db.users.find_one(
        {"_id": result.inserted_id}, {"password_hash": 0}
    )
    created["id"] = str(created.pop("_id"))
    for field in ("created_at", "updated_at", "last_login"):
        val = created.get(field)
        if isinstance(val, datetime):
            created[field] = val.isoformat()

    return jsonify(created), 201


@admin_bp.put("/users/<user_id>")
@jwt_required()
@roles_required("super_admin")
def update_user(user_id):
    """PUT /api/v1/admin/users/<user_id>"""
    data = request.get_json(silent=True) or {}

    try:
        oid = ObjectId(user_id)
    except Exception:
        return jsonify({"error": "Invalid user ID"}), 400

    user = mongo.db.users.find_one({"_id": oid})
    if not user:
        return jsonify({"error": "User not found"}), 404

    allowed = ["full_name", "email", "role", "branch", "is_active"]
    updates = {k: v for k, v in data.items() if k in allowed}

    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400

    valid_roles = [
        "super_admin", "branch_manager",
        "loan_officer", "cashier", "member",
    ]
    if "role" in updates and updates["role"] not in valid_roles:
        return jsonify({"error": "Invalid role"}), 400

    updates["updated_at"] = datetime.utcnow()
    mongo.db.users.update_one({"_id": oid}, {"$set": updates})

    updated = mongo.db.users.find_one({"_id": oid}, {"password_hash": 0})
    updated["id"] = str(updated.pop("_id"))
    for field in ("created_at", "updated_at", "last_login"):
        val = updated.get(field)
        if isinstance(val, datetime):
            updated[field] = val.isoformat()

    return jsonify(updated), 200