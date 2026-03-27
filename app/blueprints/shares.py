# backend/app/blueprints/shares.py
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from ..services.share_service import ShareService
from ..middleware.auth_middleware import roles_required

shares_bp = Blueprint("shares", __name__)
service = ShareService()


@shares_bp.get("/")
@jwt_required()
def list_shares():
    """
    GET /api/v1/shares
    Query params: page, per_page, member_id, search
    Accessible to all authenticated roles.
    """
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    member_id = request.args.get("member_id")
    search = request.args.get("search")

    result = service.get_shares(
        page=page,
        per_page=per_page,
        member_id=member_id,
        search=search,
    )
    return jsonify(result), 200


@shares_bp.get("/<share_id>")
@jwt_required()
def get_share(share_id: str):
    """GET /api/v1/shares/<share_id>  e.g. SH-2024-0001"""
    record = service.get_by_share_id(share_id)
    if not record:
        return jsonify({"error": "Share record not found"}), 404
    return jsonify(record), 200


@shares_bp.get("/member/<member_id>")
@jwt_required()
def get_share_by_member(member_id: str):
    """
    GET /api/v1/shares/member/<member_id>
    Convenience endpoint — fetch share record by member_id directly.
    """
    record = service.get_by_member_id(member_id)
    if not record:
        return jsonify({"error": "Share record not found for this member"}), 404
    return jsonify(record), 200


@shares_bp.get("/<share_id>/payments")
@jwt_required()
def get_payments(share_id: str):
    """
    GET /api/v1/shares/<share_id>/payments
    Returns the full payment history for a share record.
    """
    result = service.get_payments(share_id)
    if not result:
        return jsonify({"error": "Share record not found"}), 404
    return jsonify(result), 200


@shares_bp.put("/<share_id>/subscribe")
@jwt_required()
@roles_required("super_admin", "branch_manager", "loan_officer")
def update_subscription(share_id: str):
    """
    PUT /api/v1/shares/<share_id>/subscribe
    Increases a member's subscribed share count.
    No money changes hands — use POST /payments to record actual payment.
    Body: { "additional_shares": int, "remarks"?: str }
    """
    data = request.get_json(silent=True) or {}
    updated_by = get_jwt_identity()

    result = service.update_subscription(share_id, data, updated_by=updated_by)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 200


@shares_bp.post("/<share_id>/payments")
@jwt_required()
@roles_required("super_admin", "branch_manager", "cashier")
def record_payment(share_id: str):
    """
    POST /api/v1/shares/<share_id>/payments
    Records a share capital payment (cash received from member).
    Body: { amount_paid, or_number, payment_date?, remarks? }
    amount_paid must be a multiple of ₱100 (par value per share).
    """
    data = request.get_json(silent=True) or {}
    posted_by = get_jwt_identity()

    result = service.record_payment(share_id, data, posted_by=posted_by)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 201


@shares_bp.post("/dividends")
@jwt_required()
@roles_required("super_admin", "branch_manager")
def distribute_dividends():
    """
    POST /api/v1/shares/dividends
    Declares and distributes dividends to all members with paid-up shares.
    Body: { "dividend_rate": float, "fiscal_year": int, "remarks"?: str }
    Can only be run once per fiscal year.
    """
    data = request.get_json(silent=True) or {}
    declared_by = get_jwt_identity()

    result = service.distribute_dividends(data, declared_by=declared_by)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 200