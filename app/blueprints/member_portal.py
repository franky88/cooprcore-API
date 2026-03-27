from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from ..services.member_portal_service import MemberPortalService

member_portal_bp = Blueprint("member_portal", __name__)
service = MemberPortalService()


def _member_only():
    claims = get_jwt()
    return claims.get("role") == "member"


@member_portal_bp.get("/me")
@jwt_required()
def get_my_profile():
    if not _member_only():
        return jsonify({"error": "Member access only"}), 403

    result = service.get_member_profile_by_user_id(get_jwt_identity())
    if not result:
        return jsonify({"error": "Member profile not found"}), 404

    return jsonify({"data": result}), 200


@member_portal_bp.get("/dashboard")
@jwt_required()
def get_my_dashboard():
    if not _member_only():
        return jsonify({"error": "Member access only"}), 403

    result = service.get_dashboard_summary(get_jwt_identity())
    if not result:
        return jsonify({"error": "Member dashboard not found"}), 404

    return jsonify({"data": result}), 200


@member_portal_bp.get("/loans")
@jwt_required()
def get_my_loans():
    if not _member_only():
        return jsonify({"error": "Member access only"}), 403

    result = service.get_member_loans(get_jwt_identity())
    if not result:
        return jsonify({"error": "Member loans not found"}), 404

    return jsonify(result), 200


@member_portal_bp.get("/savings")
@jwt_required()
def get_my_savings():
    if not _member_only():
        return jsonify({"error": "Member access only"}), 403

    result = service.get_member_savings(get_jwt_identity())
    if not result:
        return jsonify({"error": "Member savings not found"}), 404

    return jsonify(result), 200


@member_portal_bp.get("/shares")
@jwt_required()
def get_my_shares():
    if not _member_only():
        return jsonify({"error": "Member access only"}), 403

    result = service.get_member_shares(get_jwt_identity())
    if result is None:
        return jsonify({"error": "Member shares not found"}), 404

    return jsonify(result), 200