"""Auth and access guard helpers."""

from pathlib import Path

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.admin.governance.admin_access_service import is_global_admin

from ...http_security import API_KEY_HEADER, validate_same_origin_request
from ...models import Session as AgentSession
from ...models import User
from ...services.session.workspace import (
    ensure_session_workspace_root,
    get_session_workspace_base_dir,
)
from .cookie_principal import require_active_api_principal
from .permissions import require_global_admin, require_permission
from .workspace_artifacts import _chat_upload_root, _office_template_upload_root, _path_within_root

WORKSPACE_ROOT = Path(__file__).resolve().parents[4]

__all__ = [
    "_chat_app_index_path",
    "_chat_app_missing_response",
    "_require_api_user",
    "_require_active_api_user",
    "_resolve_user_artifact_context",
    "_is_inline_global_artifact_blocked",
    "_require_admin_api",
    "_require_admin_permission_api",
    "_enforce_same_origin_for_cookie_auth",
]


def _has_bearer_authorization(request: Request) -> bool:
    authorization = str(request.headers.get("authorization") or "").strip()
    scheme, _, token = authorization.partition(" ")
    return scheme.lower() == "bearer" and bool(token.strip())


def _enforce_same_origin_for_cookie_auth(
    request: Request,
    *,
    cookie_names: tuple[str, ...] = ("access_token",),
) -> None:
    """Same-origin rule for the ``/api/v1/auth`` cookie routes.

    The exemption order mirrors that surface's own resolver,
    :func:`app.services.auth.get_current_user`, which takes ``X-API-Key`` first,
    then a bearer token, and only then the cookie: there, a request carrying an
    API key or a bearer token is genuinely not authenticated by the cookie. The
    panel surface resolves the *other* way round (cookie first, and it never
    authenticates an API key), so its boundary
    (:mod:`app.panel_csrf_policy`) deliberately orders these branches the
    opposite way. Each policy follows the credential its own routes use.
    """
    if str(request.headers.get(API_KEY_HEADER) or "").strip():
        return
    if _has_bearer_authorization(request):
        return
    if any(str(request.cookies.get(cookie_name) or "").strip() for cookie_name in cookie_names):
        validate_same_origin_request(request)


# Lazy import to avoid circular deps at module level
def _chat_app_dir() -> Path:
    from pathlib import Path as _Path

    return _Path(__file__).resolve().parents[1] / "static" / "chat"


def _chat_app_index_path() -> Path:
    return _chat_app_dir() / "index.html"


def _office_sample_root() -> Path:
    return (WORKSPACE_ROOT / "data" / "office-samples").resolve()


def _resolve_global_artifact_root(resolved: Path) -> Path | None:
    for root in (_chat_upload_root(), _office_template_upload_root(), _office_sample_root()):
        if _path_within_root(resolved, root):
            return root
    return None


def _is_inline_global_artifact_blocked(resolved: Path, context_root: Path) -> bool:
    global_root = _resolve_global_artifact_root(resolved)
    if global_root is None or context_root.resolve() != global_root.resolve():
        return False
    return resolved.suffix.lower() in {".html", ".htm"}


def _chat_app_missing_response():
    from fastapi.responses import HTMLResponse

    return HTMLResponse(
        """
        <html>
            <body style="background:#0f1117;color:#e2e8f0;font-family:system-ui,sans-serif;padding:32px;">
                <h1 style="margin:0 0 12px;">Chat frontend is not built</h1>
                <p style="margin:0;color:#94a3b8;">
                    Run <code>npm install && npm run build</code> in <code>frontend/chat</code>.
                </p>
            </body>
        </html>
        """,
        status_code=503,
    )


async def _require_api_user(request: Request, db: AsyncSession) -> User:
    """Active cookie/bearer principal for a JSON surface, or 401.

    Every admin-panel guard below funnels through this function, so the active
    check belongs here and not at each of the ~250 panel mutation routes: a
    deactivated account is refused with the same 401 and the same detail the
    authenticated API returns, before the route evaluates a role, a permission,
    a Workspace scope, or touches a service.
    """
    return await require_active_api_principal(request, db)


#: A second name for the same authoritative guard: the workflow-definition panel
#: and its structural gate name it directly.
_require_active_api_user = _require_api_user


async def _resolve_user_artifact_context(
    db: AsyncSession,
    user: User,
    raw_path: str,
) -> tuple[Path, Path]:
    candidate = Path(raw_path).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (WORKSPACE_ROOT / candidate).resolve()
    session_workspace_base_dir = await get_session_workspace_base_dir(db)
    if _path_within_root(resolved, session_workspace_base_dir):
        relative_to_base = resolved.relative_to(session_workspace_base_dir)
        if not relative_to_base.parts:
            raise HTTPException(status_code=403, detail="Artifact path must stay inside a session workspace")
        session_id = relative_to_base.parts[0]
        session = await db.get(AgentSession, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Artifact session not found")
        if session.user_id != user.id and not await is_global_admin(db, user.id):
            raise HTTPException(status_code=403, detail="Artifact path is not accessible for this user")
        if session.user_id != user.id and session.project_id:
            from ...services.project.private_workspace import refuse_foreign_private  # noqa: PLC0415

            if await refuse_foreign_private(db, session.project_id, str(user.id)):
                raise HTTPException(status_code=403, detail="Artifact path is not accessible for this user")
        workspace_root = await ensure_session_workspace_root(db, session, create=False)
        if not _path_within_root(resolved, workspace_root):
            raise HTTPException(status_code=403, detail="Artifact path must stay inside the session workspace")
        return resolved, workspace_root
    global_root = _resolve_global_artifact_root(resolved)
    if global_root is not None:
        if not await is_global_admin(db, user.id):
            raise HTTPException(status_code=403, detail="Global artifact access requires admin role")
        return resolved, global_root
    raise HTTPException(status_code=403, detail="Artifact path must stay inside an allowed workspace")


async def _require_admin_api(request: Request, db: AsyncSession) -> User:
    user = await _require_api_user(request, db)
    await require_global_admin(db, user, detail="Admin role required")
    return user


async def _require_admin_permission_api(
    request: Request,
    db: AsyncSession,
    *,
    resource: str,
    action: str,
) -> User:
    user = await _require_api_user(request, db)
    await require_permission(db, user, resource=resource, action=action)
    return user
