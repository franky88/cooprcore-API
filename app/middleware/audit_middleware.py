# backend/app/middleware/audit_middleware.py
from datetime import datetime
from flask import request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from ..extensions import mongo


def log_audit(
    action: str,
    resource: str,
    resource_id: str,
    details: dict | None = None,
) -> None:
    """
    Write an audit log entry. Call this from service methods after
    any state-changing operation (create, update, approve, release, etc.).

    actor_id is inferred from the JWT in the current request context.
    Safe to call outside a request context (e.g. scripts) — actor_id will
    be "system" if no JWT is present.
    """
    actor_id = "system"
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if identity:
            actor_id = identity
    except Exception:
        pass

    entry = {
        "actor_id": actor_id,
        "action": action,           # e.g. "CREATE_MEMBER", "APPROVE_LOAN"
        "resource": resource,       # e.g. "members", "loans"
        "resource_id": resource_id, # the entity's human-readable ID
        "ip_address": request.remote_addr if request else None,
        "details": details or {},
        "created_at": datetime.utcnow(),
    }

    try:
        mongo.db.audit_logs.insert_one(entry)
    except Exception:
        # Audit logging must never crash the main request
        pass