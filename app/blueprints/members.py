# backend/app/blueprints/members.py
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from ..services.member_service import MemberService
from ..middleware.auth_middleware import roles_required

members_bp = Blueprint("members", __name__)
service = MemberService()

# Roles allowed to register or update a member
_WRITE_ROLES = ("super_admin", "branch_manager", "loan_officer")
_DEACTIVATE_ROLES = ("super_admin", "branch_manager")

@members_bp.get("/")
@jwt_required()
def list_members():
    """
    GET /api/v1/members
    Query params: page, per_page, status, membership_type, search
    Accessible to all authenticated roles.
    """
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    status = request.args.get("status")
    membership_type = request.args.get("membership_type")
    search = request.args.get("search")

    result = service.get_members(
        page=page,
        per_page=per_page,
        status=status,
        membership_type=membership_type,
        search=search,
    )
    return jsonify(result), 200


@members_bp.get("/<member_id>")
@jwt_required()
def get_member(member_id: str):
    """
    GET /api/v1/members/<member_id>
    e.g. GET /api/v1/members/M-2024-0001
    """
    member = service.get_by_member_id(member_id)
    if not member:
        return jsonify({"error": "Member not found"}), 404
    return jsonify(member), 200


@members_bp.get("/<member_id>/summary")
@jwt_required()
def get_member_summary(member_id: str):
    """
    GET /api/v1/members/<member_id>/summary
    Returns the member's profile + active loans, savings accounts,
    share capital summary, and computed totals.
    """
    result = service.get_member_summary(member_id)
    if not result:
        return jsonify({"error": "Member not found"}), 404
    return jsonify(result), 200


@members_bp.post("/")
@jwt_required()
@roles_required(*_WRITE_ROLES)
def create_member():
    """
    POST /api/v1/members
    Registers a new member. Auto-provisions a Regular Savings account
    and a Share Capital record on success.
    """
    data = request.get_json(silent=True) or {}
    created_by = get_jwt_identity()

    result = service.create_member(data, created_by=created_by)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 201


@members_bp.put("/<member_id>")
@jwt_required()
@roles_required(*_WRITE_ROLES)
def update_member(member_id: str):
    """
    PUT /api/v1/members/<member_id>
    Partial update — only provided fields are changed.
    """
    data = request.get_json(silent=True) or {}
    updated_by = get_jwt_identity()

    result = service.update_member(member_id, data, updated_by=updated_by)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 200



@members_bp.post("/<member_id>/deactivate")
@jwt_required()
@roles_required(*_DEACTIVATE_ROLES)
def deactivate_member(member_id: str):
    """
    POST /api/v1/members/<member_id>/deactivate
    Soft-deactivates a member by setting status to Inactive.

    This preserves:
    - loans
    - savings accounts
    - share capital records
    - audit trail

    Hard delete is not allowed.
    """
    updated_by = get_jwt_identity()

    result = service.deactivate_member(member_id, updated_by=updated_by)
    if "error" in result:
        return jsonify(result), 400

    return jsonify(result), 200