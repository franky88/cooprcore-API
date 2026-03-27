# backend/app/blueprints/users.py
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from ..services.user_service import UserService
from ..middleware.auth_middleware import roles_required

users_bp = Blueprint("users", __name__)
service = UserService()


@users_bp.get("/")
@jwt_required()
@roles_required("super_admin")
def list_users():
    """
    GET /api/v1/users
    Query params: page, per_page, role, is_active, search
    """
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    role = request.args.get("role")
    search = request.args.get("search")

    # Parse is_active as bool — absent means no filter
    is_active_raw = request.args.get("is_active")
    is_active = None
    if is_active_raw is not None:
        is_active = is_active_raw.lower() == "true"

    result = service.get_users(
        page=page,
        per_page=per_page,
        role=role,
        is_active=is_active,
        search=search,
    )
    return jsonify(result), 200


@users_bp.get("/<user_id>")
@jwt_required()
@roles_required("super_admin")
def get_user(user_id: str):
    """
    GET /api/v1/users/<user_id>
    """
    user = service.get_by_id(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify(user), 200


@users_bp.post("/")
@jwt_required()
@roles_required("super_admin")
def create_user():
    """
    POST /api/v1/users
    Body: { full_name, email, password, role, branch? }
    """
    data = request.get_json(silent=True) or {}
    created_by = get_jwt_identity()

    result = service.create_user(data, created_by=created_by)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 201


@users_bp.put("/<user_id>")
@jwt_required()
@roles_required("super_admin")
def update_user(user_id: str):
    """
    PUT /api/v1/users/<user_id>
    Body: any subset of { full_name, role, branch, is_active }
    """
    data = request.get_json(silent=True) or {}
    updated_by = get_jwt_identity()

    result = service.update_user(user_id, data, updated_by=updated_by)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 200


@users_bp.post("/<user_id>/reset-password")
@jwt_required()
@roles_required("super_admin")
def reset_password(user_id: str):
    """
    POST /api/v1/users/<user_id>/reset-password
    Body: { "new_password": str }
    super_admin only — bypasses current password requirement.
    """
    data = request.get_json(silent=True) or {}
    new_password = data.get("new_password", "")

    if not new_password:
        return jsonify({"error": {"new_password": ["new_password is required"]}}), 400

    result = service.admin_reset_password(user_id, new_password)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 200


@users_bp.put("/me/change-password")
@jwt_required()
def change_my_password():
    """
    PUT /api/v1/users/me/change-password
    Body: { "current_password": str, "new_password": str }
    Uses the authenticated user's JWT identity.
    """
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}

    result = service.change_password(user_id, data)
    if "error" in result:
        return jsonify(result), 400

    return jsonify(result), 200


@users_bp.delete("/<user_id>")
@jwt_required()
@roles_required("super_admin")
def deactivate_user(user_id: str):
    """
    DELETE /api/v1/users/<user_id>
    Soft-delete only — sets is_active=False.
    Hard deletes are not permitted to preserve audit trail integrity.
    A super_admin cannot deactivate themselves.
    """
    requesting_user_id = get_jwt_identity()
    if requesting_user_id == user_id:
        return jsonify({"error": "You cannot deactivate your own account"}), 400

    result = service.update_user(
        user_id,
        {"is_active": False},
        updated_by=requesting_user_id,
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify({"message": "User deactivated successfully"}), 200
