"""A per-repository Git token for a Bitbucket Data Center repository of a Workspace. Git over HTTPS refuses the OIDC
Bearer token, so the clone needs its own token."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog, KnowledgeSourceConnector, RepositoryGitToken
from ....models.project.knowledge_source_sync import CONNECTOR_KIND_GIT_REPOSITORY
from ....time_utils import utc_now
from ...outbound_egress import CONNECTION_BITBUCKET, EgressRefusedError, egress_transport
from ...secret import get_secret_value, set_secret_value
from ...secret.release import release_unreferenced_secrets
from ..ledger.errors import InvalidEvidenceRequestError
from .repository_access import RepositoryIdentity
from .sync.contract import (
    REASON_EGRESS_REFUSED,
    REASON_GIT_TOKEN_INVALID,
    REASON_GIT_TOKEN_NOT_SUPPORTED,
    REASON_GIT_TOKEN_WRONG_REPOSITORY,
    REASON_SOURCE_CONTRACT_VIOLATION,
    REASON_SOURCE_RATE_LIMITED,
    REASON_SOURCE_UNAVAILABLE,
    ConnectorError,
)
from .sync.git_config import HOST_BASE, HOST_KIND
from .sync.git_hosts import HOST_BITBUCKET_DATACENTER, parse_datacenter_repository
from .sync.utc import utc_iso

logger = logging.getLogger(__name__)

GIT_TOKEN_SET_AUDIT_ACTION = "knowledge_source.git_token_set"
GIT_TOKEN_REMOVED_AUDIT_ACTION = "knowledge_source.git_token_removed"
SECRET_TOOL_NAME = "repository_git_token"
REMOVED_BY_AUTHOR = "removed"
REMOVED_WITH_SOURCE = "source_deleted"
TIMEOUT_SECONDS = 30.0
# A Bitbucket HTTP access token is printable ASCII without spaces; anything else is no token (nothing is sent).
_TOKEN = re.compile(r"^[\x21-\x7e]{8,1024}$")
_RECEIVE_PACK_ADVERTISEMENT = "application/x-git-receive-pack-advertisement"
_MAX_ANSWER_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class CheckedGitToken:
    # The token value never appears in a repr.
    repository: RepositoryIdentity
    token: str = field(repr=False)


def repository_key(identity: RepositoryIdentity) -> str:
    return f"bitbucket:{identity.path}"


def source_repository(scope: dict | None) -> RepositoryIdentity | None:
    scope = dict(scope or {})
    if scope.get(HOST_KIND) != HOST_BITBUCKET_DATACENTER:
        return None
    base = str(scope.get(HOST_BASE) or "")
    try:
        return RepositoryIdentity(base, parse_datacenter_repository(scope.get("remote"), base).path)
    except InvalidEvidenceRequestError:
        return None


def _status_reason(status: int) -> str:
    if status == 401:
        return REASON_GIT_TOKEN_INVALID
    if status in (403, 404):
        return REASON_GIT_TOKEN_WRONG_REPOSITORY
    if status == 429:
        return REASON_SOURCE_RATE_LIMITED
    return REASON_SOURCE_UNAVAILABLE if status >= 500 else REASON_SOURCE_CONTRACT_VIOLATION



async def check_git_token(
    repository: RepositoryIdentity | None, token: object, *, transport: httpx.AsyncBaseTransport | None = None
) -> CheckedGitToken:
    if repository is None:
        raise ConnectorError(REASON_GIT_TOKEN_NOT_SUPPORTED)
    if type(token) is not str or not _TOKEN.fullmatch(token):
        raise ConnectorError(REASON_GIT_TOKEN_INVALID)
    key, slug = repository.path.split("/", 1)
    url = (f"{repository.base.rstrip('/')}/scm/{quote(key.lower(), safe='~')}/{quote(slug.lower(), safe='')}.git"
           "/info/refs?service=git-receive-pack")
    try:
        async with httpx.AsyncClient(
            transport=egress_transport(CONNECTION_BITBUCKET, inner=transport), timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    except EgressRefusedError:
        raise ConnectorError(REASON_EGRESS_REFUSED) from None
    except httpx.HTTPError:
        raise ConnectorError(REASON_SOURCE_UNAVAILABLE) from None
    if response.status_code != 200:
        raise ConnectorError(_status_reason(response.status_code))
    if response.headers.get("content-type", "").split(";")[0].strip() != _RECEIVE_PACK_ADVERTISEMENT:
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)  # a login page or proxy answer, not Git
    return CheckedGitToken(repository=repository, token=token)


async def _token_row(db: AsyncSession, project_id: str, repository: RepositoryIdentity) -> RepositoryGitToken | None:
    return (await db.execute(select(RepositoryGitToken).where(
        RepositoryGitToken.project_id == project_id,
        RepositoryGitToken.host_base == repository.base,
        RepositoryGitToken.repository_key == repository_key(repository),
    ))).scalar_one_or_none()


def _secret_field(row_id: str) -> str:
    return f"git_token:{row_id}"


def _audit(db: AsyncSession, action: str, *, actor_id: str | None, connector: KnowledgeSourceConnector,
           repository: RepositoryIdentity, **details: Any) -> None:
    db.add(AuditLog(
        user_id=actor_id, action=action, resource_type="knowledge_source_connector", resource_id=connector.id,
        project_id=connector.project_id,
        details={"workspace_id": connector.project_id, "connector_key": connector.connector_key,
                 "repository_key": repository_key(repository), "host_base": repository.base, **details},
    ))


async def store_git_token(
    db: AsyncSession, *, connector: KnowledgeSourceConnector, checked: CheckedGitToken, actor_id: str
) -> RepositoryGitToken:
    project_id = str(connector.project_id)
    row = await _token_row(db, project_id, checked.repository)
    replaced = row is not None
    if row is None:
        row = RepositoryGitToken(id=str(uuid.uuid4()), project_id=project_id, host_base=checked.repository.base,
                                 repository_key=repository_key(checked.repository))
    secret = await set_secret_value(db, tool_name=SECRET_TOOL_NAME, field_name=_secret_field(row.id),
                                    project_id=project_id, value=checked.token)
    row.secret_id, row.set_by, row.set_at = secret.id, actor_id, utc_now()
    if not replaced:
        db.add(row)
    await db.flush()
    _audit(db, GIT_TOKEN_SET_AUDIT_ACTION, actor_id=actor_id, connector=connector, repository=checked.repository,
           replaced=replaced)
    return row


async def remove_git_token(
    db: AsyncSession, *, connector: KnowledgeSourceConnector, actor_id: str | None, reason: str = REMOVED_BY_AUTHOR
) -> bool:
    repository = source_repository(connector.scope)
    row = None if repository is None else await _token_row(db, str(connector.project_id), repository)
    if row is None or repository is None:
        return False
    secret_id = row.secret_id
    await db.delete(row)
    await db.flush()
    await release_unreferenced_secrets(db, [secret_id])
    _audit(db, GIT_TOKEN_REMOVED_AUDIT_ACTION, actor_id=actor_id, connector=connector, repository=repository,
           reason=reason)
    return True


async def remove_git_token_with_source(db: AsyncSession, *, connector: KnowledgeSourceConnector,
                                       actor_id: str | None) -> bool:
    repository = source_repository(connector.scope)
    if repository is None:
        return False
    others = (await db.execute(select(KnowledgeSourceConnector.scope).where(
        KnowledgeSourceConnector.project_id == connector.project_id,
        KnowledgeSourceConnector.kind == CONNECTOR_KIND_GIT_REPOSITORY,
        KnowledgeSourceConnector.id != connector.id,
    ))).scalars().all()
    if any(source_repository(scope) == repository for scope in others):
        return False
    return await remove_git_token(db, connector=connector, actor_id=actor_id, reason=REMOVED_WITH_SOURCE)


async def git_token_state(db: AsyncSession, project_id: str, scope: dict | None) -> dict[str, Any]:
    repository = source_repository(scope)
    row = None if repository is None else await _token_row(db, project_id, repository)
    if row is None:
        return {"configured": False}
    return {"configured": True, "set_at": utc_iso(row.set_at), "set_by": row.set_by}


async def usable_git_token(
    db: AsyncSession, project_id: str | None, repository: RepositoryIdentity | None
) -> str | None:
    # Only the secret service decrypts; nothing is logged.
    if not project_id or repository is None:
        return None
    row = await _token_row(db, project_id, repository)
    if row is None:
        return None
    value = await get_secret_value(db, secret_id=row.secret_id, expected_tool_name=SECRET_TOOL_NAME,
                                   expected_field_name=_secret_field(row.id), expected_project_id=project_id,
                                   purpose="knowledge.repository_git_token")
    if not value:
        logger.warning("Repository Git token not usable (revoked or expired): workspace=%s repository=%s",
                       project_id, repository_key(repository))
        return None
    return value


__all__ = [
    "GIT_TOKEN_REMOVED_AUDIT_ACTION",
    "GIT_TOKEN_SET_AUDIT_ACTION",
    "CheckedGitToken",
    "check_git_token",
    "git_token_state",
    "remove_git_token",
    "remove_git_token_with_source",
    "repository_key",
    "source_repository",
    "store_git_token",
    "usable_git_token",
]
