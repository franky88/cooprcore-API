# backend/app/blueprints/savings.py
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from ..services.savings_service import SavingsService
from ..middleware.auth_middleware import roles_required

savings_bp = Blueprint("savings", __name__)
service = SavingsService()


@savings_bp.get("/")
@jwt_required()
def list_accounts():
    """
    GET /api/v1/savings
    Query params: page, per_page, member_id, product_type, status
    Accessible to all authenticated roles.
    """
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    member_id = request.args.get("member_id")
    product_type = request.args.get("product_type")
    status = request.args.get("status")

    result = service.get_accounts(
        page=page,
        per_page=per_page,
        member_id=member_id,
        product_type=product_type,
        status=status,
    )
    return jsonify(result), 200


@savings_bp.get("/<account_id>")
@jwt_required()
def get_account(account_id: str):
    """GET /api/v1/savings/<account_id>  e.g. SA-2024-0001"""
    account = service.get_by_account_id(account_id)
    if not account:
        return jsonify({"error": "Account not found"}), 404
    return jsonify(account), 200


@savings_bp.get("/<account_id>/ledger")
@jwt_required()
def get_ledger(account_id: str):
    """
    GET /api/v1/savings/<account_id>/ledger
    Query params: page, per_page
    Returns paginated transaction history.
    """
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))

    result = service.get_ledger(account_id, page=page, per_page=per_page)
    if not result:
        return jsonify({"error": "Account not found"}), 404
    return jsonify(result), 200


@savings_bp.post("/")
@jwt_required()
@roles_required("super_admin", "branch_manager")
def open_account():
    """
    POST /api/v1/savings
    Opens a new savings account for a member.
    Body: { member_id, product_type, initial_deposit?, passbook_number?,
            term_months? (TD only), placement_amount? (TD only) }
    """
    data = request.get_json(silent=True) or {}
    opened_by = get_jwt_identity()

    result = service.open_account(data, opened_by=opened_by)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 201


@savings_bp.put("/<account_id>")
@jwt_required()
@roles_required("super_admin", "branch_manager")
def update_account(account_id: str):
    """
    PUT /api/v1/savings/<account_id>
    Updates non-financial account metadata: status, passbook_number, interest_rate.
    """
    data = request.get_json(silent=True) or {}
    updated_by = get_jwt_identity()

    result = service.update_account(account_id, data, updated_by=updated_by)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 200


@savings_bp.post("/<account_id>/transactions")
@jwt_required()
@roles_required("super_admin", "branch_manager", "cashier")
def post_transaction(account_id: str):
    """
    POST /api/v1/savings/<account_id>/transactions
    Posts a Deposit or Withdrawal.
    Body: { transaction_type, amount, payment_method, or_number,
            reference_number?, transaction_date?, remarks? }
    """
    data = request.get_json(silent=True) or {}
    posted_by = get_jwt_identity()

    result = service.post_transaction(account_id, data, posted_by=posted_by)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 201


@savings_bp.post("/interest")
@jwt_required()
@roles_required("super_admin", "branch_manager")
def post_interest():
    """
    POST /api/v1/savings/interest
    Triggers monthly interest posting.
    Body: { account_id? | product_type?, as_of_date? }
    If neither account_id nor product_type is given, posts to all eligible accounts.
    """
    data = request.get_json(silent=True) or {}
    posted_by = get_jwt_identity()

    result = service.post_interest(data, posted_by=posted_by)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 200


@savings_bp.post("/dormancy-check")
@jwt_required()
@roles_required("super_admin", "branch_manager")
def dormancy_check():
    """
    POST /api/v1/savings/dormancy-check
    Marks accounts with no activity in 12+ months as Dormant.
    Intended to be called by a scheduled job or manually by a manager.
    """
    result = service.mark_dormant_accounts()
    return jsonify(result), 200