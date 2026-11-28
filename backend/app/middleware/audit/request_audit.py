import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Request
from sqlalchemy import select

from ...db import async_session_factory
from ...models import AuditLog, User
from ...services.audit_trail.request_scope import close_request_scope, open_request_scope
from ...services.auth import resolve_bearer_principal_user_id
from ...services.request_context import get_current_request_id
from ...trusted_proxy_policy import effective_client_address

logger = logging.getLogger(__name__)
root_logger = logging.getLogger()
# Where audit rows go when the database refuses them; the test suite points it at its temp directory.
AUDIT_FALLBACK_DEFAULT_FILE = Path(__file__).resolve().parents[3] / "data" / "audit-fallback.jsonl"
_AUDIT_FALLBACK_FILE = AUDIT_FALLBACK_DEFAULT_FILE
_ANONYMOUS_AUDIT_USER_ID = "anonymous"


def _log_exception(message: str, *args: object) -> None:
    logger.exception(message, *args)
    if logger.disabled or not logger.propagate:
        root_logger.exception(message, *args)


def _append_audit_fallback(payload: dict) -> None:
    _AUDIT_FALLBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _AUDIT_FALLBACK_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, default=str) + "\n")


async def _ensure_anonymous_audit_user(db) -> None:
    existing = (
        await db.execute(select(User.id).where(User.id == _ANONYMOUS_AUDIT_USER_ID))
    ).scalar_one_or_none()
    if existing:
        return
    db.add(
        User(
            id=_ANONYMOUS_AUDIT_USER_ID,
            username="anonymous",
            email="anonymous@octryx.local",
            password_hash="disabled-audit-principal",
            auth_source="system",
            account_type="system",
            display_name="Anonymous Audit Principal",
            is_active=False,
        )
    )


_UUID_SEGMENT = re.compile(r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?=/|$)")


# The route parameters that name a Workspace: a generic row of a Workspace route belongs to that Workspace.
_WORKSPACE_PATH_PARAMS = ("project_id", "workspace_id")


def _route_workspace(request: Request) -> str | None:
    params = request.path_params
    return next((str(params[name]) for name in _WORKSPACE_PATH_PARAMS if params.get(name)), None)


def _route_action(request: Request) -> str:
    return f"{request.method} {_UUID_SEGMENT.sub('/{id}', request.url.path)}"


async def audit_middleware(request: Request, call_next):
    """Audit a mutating request that wrote no domain audit event itself (one event per change)."""
    scope = open_request_scope()
    try:
        response = await call_next(request)
    finally:
        close_request_scope()
    request_id = getattr(request.state, "request_id", None) or get_current_request_id()

    if request.method in ("POST", "PUT", "DELETE", "PATCH") and not scope["domain_events"]:
        auth_header = request.headers.get("authorization")
        token = auth_header.split(" ", 1)[1] if auth_header and auth_header.startswith("Bearer ") else ""
        log_user_id = _ANONYMOUS_AUDIT_USER_ID
        try:
            app = request.scope.get("app")
            session_factory = getattr(getattr(app, "state", None), "async_session_factory", async_session_factory)
            async with session_factory() as db:
                if token:
                    try:
                        log_user_id = await resolve_bearer_principal_user_id(db, token)
                    except Exception:
                        # Log anonymous requests too; invalid Bearer auth must not drop audit records.
                        _log_exception("Failed to decode token for audit middleware (request_id=%s)", request_id)
                if log_user_id == _ANONYMOUS_AUDIT_USER_ID:
                    await _ensure_anonymous_audit_user(db)
                log = AuditLog(
                    user_id=log_user_id,
                    action=_route_action(request),
                    resource_type="api",
                    project_id=_route_workspace(request),
                    ip_address=effective_client_address(request),
                    details={"status_code": response.status_code, "request_id": request_id or "",
                             "path": request.url.path},
                )
                db.add(log)
                await db.commit()
        except Exception:
            _log_exception("Failed to persist audit log entry (request_id=%s)", request_id)
            try:
                _append_audit_fallback(
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "request_id": request_id or "",
                        "user_id": log_user_id,
                        "action": _route_action(request),
                        "resource_type": "api",
                        "ip_address": effective_client_address(request),
                        "status_code": response.status_code,
                    }
                )
            except Exception:
                _log_exception("Failed to persist audit fallback entry (request_id=%s)", request_id)

    return response
