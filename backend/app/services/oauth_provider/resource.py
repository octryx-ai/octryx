"""Resource-server-side verification of platform-issued OAuth access tokens."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...models.security.oauth_provider import OAuthGrant
from .tokens import DEFAULT_RESOURCE_AUDIENCE, verify_access_token_for_audiences


@dataclass(frozen=True)
class OAuthResourceContext:
    user_id: str
    grant_id: str
    oauth_client_id: str
    scopes: tuple[str, ...]
    bound_project_ids: tuple[str, ...] | None

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


def acceptable_mcp_audiences(*, mount_path: str, streamable_path: str) -> set[str]:
    """Audiences accepted by the MCP resource server."""
    settings = get_settings()
    resource_suffix = f"{mount_path}{streamable_path}"
    return {
        DEFAULT_RESOURCE_AUDIENCE,
        f"http://localhost:{settings.port}{resource_suffix}",
        f"http://127.0.0.1:{settings.port}{resource_suffix}",
    }


async def resolve_oauth_resource_context(
    db: AsyncSession,
    *,
    token: str,
    audiences: set[str],
) -> OAuthResourceContext | None:
    """Validate the JWT and the underlying grant; None means unauthorized."""
    claims = verify_access_token_for_audiences(token, audiences=audiences)
    if claims is None:
        return None
    grant_id = str(claims.get("grant_id") or "").strip()
    user_id = str(claims.get("sub") or "").strip()
    if not grant_id or not user_id:
        return None
    grant = await db.get(OAuthGrant, grant_id)
    if grant is None or grant.revoked_at is not None or grant.user_id != user_id:
        return None
    scopes = tuple(item for item in str(claims.get("scope") or "").split() if item)
    project_ids = grant.project_ids
    bound = tuple(str(item) for item in project_ids) if isinstance(project_ids, list) and project_ids else None
    return OAuthResourceContext(
        user_id=user_id,
        grant_id=grant_id,
        oauth_client_id=str(claims.get("client_id") or ""),
        scopes=scopes,
        bound_project_ids=bound,
    )
