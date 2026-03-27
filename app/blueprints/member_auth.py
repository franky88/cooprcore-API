from flask import Blueprint, jsonify, request

from ..schemas.member_auth_schema import (
    MemberActivationStartSchema,
    MemberActivationCompleteSchema,
)
from ..services.member_auth_service import MemberAuthService

member_auth_bp = Blueprint("member_auth", __name__)
service = MemberAuthService()

start_schema = MemberActivationStartSchema()
complete_schema = MemberActivationCompleteSchema()


@member_auth_bp.post("/activate/start")
def start_member_activation():
    payload = start_schema.load(request.get_json() or {})
    result = service.start_activation(payload)

    if "error" in result:
        return jsonify(result), 400

    return jsonify(result), 200


@member_auth_bp.post("/activate/complete")
def complete_member_activation():
    payload = complete_schema.load(request.get_json() or {})
    result = service.complete_activation(payload)

    if "error" in result:
        return jsonify(result), 400

    return jsonify(result), 201