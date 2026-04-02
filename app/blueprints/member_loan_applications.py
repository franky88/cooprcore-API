from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from ..schemas.member_loan_application_schema import MemberLoanApplicationCreateSchema
from ..services.member_loan_application_service import MemberLoanApplicationService

member_loan_applications_bp = Blueprint("member_loan_applications", __name__)
service = MemberLoanApplicationService()
create_schema = MemberLoanApplicationCreateSchema()


def _member_only() -> bool:
    claims = get_jwt()
    return claims.get("role") == "member"


@member_loan_applications_bp.get("/loan-applications")
@jwt_required()
def list_my_loan_applications():
    if not _member_only():
        return jsonify({"error": "Member access only"}), 403

    result, status = service.get_member_applications(get_jwt_identity())
    return jsonify(result), status


@member_loan_applications_bp.get("/loan-applications/<application_id>")
@jwt_required()
def get_my_loan_application(application_id: str):
    if not _member_only():
        return jsonify({"error": "Member access only"}), 403

    result, status = service.get_member_application_by_id(
        get_jwt_identity(),
        application_id,
    )
    return jsonify(result), status


@member_loan_applications_bp.post("/loan-applications")
@jwt_required()
def submit_my_loan_application():
    if not _member_only():
        return jsonify({"error": "Member access only"}), 403

    payload = create_schema.load(request.get_json() or {})
    result, status = service.submit_application(
        user_id=get_jwt_identity(),
        payload=payload,
    )
    return jsonify(result), status