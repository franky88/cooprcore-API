# backend/app/blueprints/auth.py
from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    jwt_required,
    get_jwt_identity,
    create_access_token,
    get_jwt,
)
from bson import ObjectId

from ..extensions import mongo
from ..services.auth_service import AuthService

auth_bp = Blueprint("auth", __name__)
auth_service = AuthService()


@auth_bp.post("/login")
def login():
    """
    POST /api/v1/auth/login
    Public endpoint — no JWT required.
    Body: { "email": str, "password": str }
    """
    data = request.get_json(silent=True)
    result, status = auth_service.login(data or {})
    return jsonify(result), status


@auth_bp.post("/refresh")
@jwt_required(refresh=True)
def refresh():
    """
    POST /api/v1/auth/refresh
    Requires the refresh token (Bearer).
    Returns a new access token.
    """
    identity = get_jwt_identity()
    # Carry forward the same role/name claims
    user_doc = mongo.db.users.find_one(
        {"_id": ObjectId(identity)},
        {"role": 1, "full_name": 1, "employee_id": 1, "is_active": 1},
    )

    if not user_doc or not user_doc.get("is_active"):
        return jsonify({"error": "Account is deactivated"}), 403

    access_token = create_access_token(
        identity=identity,
        additional_claims={
            "role": user_doc["role"],
            "name": user_doc["full_name"],
            "employee_id": user_doc["employee_id"],
        },
    )
    return jsonify({"access_token": access_token}), 200


@auth_bp.get("/me")
@jwt_required()
def me():
    """
    GET /api/v1/auth/me
    Returns the currently authenticated user's profile.
    """
    identity = get_jwt_identity()
    user_doc = mongo.db.users.find_one(
        {"_id": ObjectId(identity)},
        {"password_hash": 0},
    )

    if not user_doc:
        return jsonify({"error": "User not found"}), 404

    user_doc["id"] = str(user_doc.pop("_id"))
    return jsonify(user_doc), 200


@auth_bp.post("/change-password")
@jwt_required()
def change_password():
    """
    POST /api/v1/auth/change-password
    Authenticated users can change their own password.
    Body: { "current_password": str, "new_password": str }
    """
    identity = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    from ..services.user_service import UserService
    result = UserService().change_password(identity, data)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 200