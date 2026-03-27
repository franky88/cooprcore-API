# backend/app/blueprints/loans.py
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from ..services.loan_service import LoanService
from ..middleware.auth_middleware import roles_required

loans_bp = Blueprint("loans", __name__)
service = LoanService()


@loans_bp.get("/")
@jwt_required()
def list_loans():
    """
    GET /api/v1/loans
    Query params: page, per_page, member_id, status, loan_type
    Accessible to all authenticated roles.
    """
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    loan_type = request.args.get("loan_type")

    result = service.get_loans(
        page=page,
        per_page=per_page,
        member_id=member_id,
        status=status,
        loan_type=loan_type,
    )
    return jsonify(result), 200


@loans_bp.get("/calculator")
@jwt_required()
def calculator():
    """
    GET /api/v1/loans/calculator?loan_type=Multi-Purpose&principal=50000&term_months=24
    Stateless — computes amortization without touching the database.
    """
    loan_type = request.args.get("loan_type", "")
    try:
        principal = float(request.args.get("principal", 0))
        term_months = int(request.args.get("term_months", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "principal and term_months must be numbers"}), 400

    result = service.calculate(loan_type, principal, term_months)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 200


@loans_bp.get("/<loan_id>")
@jwt_required()
def get_loan(loan_id: str):
    """GET /api/v1/loans/<loan_id>  e.g. LN-2024-0001"""
    loan = service.get_by_loan_id(loan_id)
    if not loan:
        return jsonify({"error": "Loan not found"}), 404
    return jsonify(loan), 200


@loans_bp.get("/<loan_id>/schedule")
@jwt_required()
def get_schedule(loan_id: str):
    """GET /api/v1/loans/<loan_id>/schedule — full amortization schedule."""
    result = service.get_schedule(loan_id)
    if not result:
        return jsonify({"error": "Loan not found"}), 404
    return jsonify(result), 200


@loans_bp.get("/<loan_id>/payments")
@jwt_required()
def get_payments(loan_id: str):
    """GET /api/v1/loans/<loan_id>/payments — payment history."""
    result = service.get_payments(loan_id)
    if not result:
        return jsonify({"error": "Loan not found"}), 404
    return jsonify(result), 200


@loans_bp.post("/")
@jwt_required()
@roles_required("super_admin", "branch_manager", "loan_officer")
def apply():
    """
    POST /api/v1/loans
    Submits a new loan application. Status is set to Pending.
    """
    data = request.get_json(silent=True) or {}
    submitted_by = get_jwt_identity()

    result = service.apply(data, submitted_by=submitted_by)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 201


@loans_bp.put("/<loan_id>/approve")
@jwt_required()
@roles_required("super_admin", "branch_manager")
def approve(loan_id: str):
    """
    PUT /api/v1/loans/<loan_id>/approve
    Moves the loan from Pending → Approved.
    """
    data = request.get_json(silent=True) or {}
    approved_by = get_jwt_identity()

    result = service.approve(loan_id, data, approved_by=approved_by)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 200


@loans_bp.put("/<loan_id>/reject")
@jwt_required()
@roles_required("super_admin", "branch_manager")
def reject(loan_id: str):
    """
    PUT /api/v1/loans/<loan_id>/reject
    Moves the loan from Pending → Rejected.
    Body: { "reason": str }
    """
    data = request.get_json(silent=True) or {}
    rejected_by = get_jwt_identity()

    result = service.reject(loan_id, data, rejected_by=rejected_by)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 200


@loans_bp.put("/<loan_id>/release")
@jwt_required()
@roles_required("super_admin", "branch_manager", "cashier")
def release(loan_id: str):
    """
    PUT /api/v1/loans/<loan_id>/release
    Disburses the loan: Approved → Current.
    Body: { "or_number": str, "remarks"?: str }
    """
    data = request.get_json(silent=True) or {}
    released_by = get_jwt_identity()

    result = service.release(loan_id, data, released_by=released_by)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 200


@loans_bp.post("/<loan_id>/payments")
@jwt_required()
@roles_required("super_admin", "branch_manager", "cashier")
def post_payment(loan_id: str):
    """
    POST /api/v1/loans/<loan_id>/payments
    Records a loan repayment. Allocates to penalty → interest → principal.
    Body: { amount_paid, payment_method, or_number, payment_date?, remarks? }
    """
    data = request.get_json(silent=True) or {}
    posted_by = get_jwt_identity()

    result = service.post_payment(loan_id, data, posted_by=posted_by)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 201