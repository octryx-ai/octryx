"""A per-repository Git token for a Bitbucket Data Center repository of a Workspace.

Why: a Data Center connection signed in with the OpenID Connect client credentials grant reads the REST API, but Git
over HTTPS (``/scm/...``) answers 500 for that Bearer token, so the server can neither clone (Knowledge sync:
``source_unauthorized``) nor push (workflow runs). An author therefore enters a Bitbucket HTTP access token
(repository or project scope, "Repository write") when registering the repository from the connection.

- **Checked before it is stored** (:func:`check_git_token`) the way Git itself uses it: the smart-HTTP push
  discovery ``GET {base}/scm/{key}/{slug}.git/info/refs?service=git-receive-pack`` with ``Authorization: Bearer
  <token>`` through the pinned egress transport of the ``bitbucket`` connection type (``public_only`` plus the
  admin's on-prem allowlist; a refusal is ``egress_refused`` and nothing is sent), no redirects. 200 with the
  receive-pack advertisement means "this token may push to exactly this repository"; 401 is ``git_token_invalid``,
  403/404 is ``git_token_wrong_repository`` (no write right there); anything else is the fixed reason of the status.
  Not the REST API: a security proxy in front of Bitbucket can take a REST Bearer for an OpenID Connect token and
  answer 401 to a valid HTTP access token, while ``/scm`` passes it to Bitbucket. A broader token (project or
  personal) is accepted as long as it may push to this repository.
- **Stored encrypted** in ``stored_secrets`` with the platform's secret service (``services/secret``: Fernet keyed
  by the instance ``encryption_key``), tool ``repository_git_token``, field ``git_token:<row id>``, the Workspace
  as its project. ``repository_git_tokens`` holds the secret's id, the instance and ``bitbucket:<KEY>/<slug>``,
  who set it and when; never the value. One token per Workspace and repository: the Knowledge sync and the workflow
  runs of that Workspace on that repository use it (:func:`usable_git_token`).
- **Never answered**: :func:`git_token_state` is ``{"configured", "set_at", "set_by"}``. Never logged; every
  dataclass that carries it hides it from ``repr``. Set, replace and remove are audited
  (``knowledge_source.git_token_set`` / ``knowledge_source.git_token_removed``) with keys and ids only.
- **Used for Git only**, and only on the instance it was checked against: the clone of the Knowledge sync
  (``sync/git_clone.py``) and the Bitbucket tools' Git environment (clone, fetch, pull, push of workflow runs).
  REST calls keep the connection's sign-in.
"""

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
    """A token Bitbucket confirmed for exactly ``repository``; the value never appears in a repr."""

    repository: RepositoryIdentity
    token: str = field(repr=False)


def repository_key(identity: RepositoryIdentity) -> str:
    """``bitbucket:<KEY>/<slug>``: the repository key of the workflow runs (``workflow_runs/platform/scm.py``)."""
    return f"bitbucket:{identity.path}"


def source_repository(scope: dict | None) -> RepositoryIdentity | None:
    """The Data Center repository of a ``git_repository`` source's scope, else ``None`` (no token applies)."""
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
    """The token, confirmed by Bitbucket for exactly ``repository`` (module doc); else :class:`ConnectorError`."""
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
        details={"workspace_id": connector.project_id, "connector_key": connector.connector_key,
                 "repository_key": repository_key(repository), "host_base": repository.base, **details},
    ))


async def store_git_token(
    db: AsyncSession, *, connector: KnowledgeSourceConnector, checked: CheckedGitToken, actor_id: str
) -> RepositoryGitToken:
    """Store (or replace) the checked token of ``connector``'s Workspace and repository; audited; never commits."""
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
    """Remove the token of ``connector``'s repository and destroy its secret; audited; ``False``: none was set."""
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
    """A deleted source takes its repository's token along unless another source of the Workspace reads it."""
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
    """What a client may know: whether a token is configured for the source's repository, when and by whom."""
    repository = source_repository(scope)
    row = None if repository is None else await _token_row(db, project_id, repository)
    if row is None:
        return {"configured": False}
    return {"configured": True, "set_at": utc_iso(row.set_at), "set_by": row.set_by}


async def usable_git_token(
    db: AsyncSession, project_id: str | None, repository: RepositoryIdentity | None
) -> str | None:
    """The decrypted token for Git on ``repository`` in the Workspace, or ``None`` (none set, revoked or expired:
    Git then signs in with the connection). Only the secret service decrypts; nothing is logged."""
    if not project_id or repository is None:
        return None
    row = await _token_row(db, project_id, repository)
    if row is None:
        return None
    value = await get_secret_value(db, secret_id=row.secret_id, expected_tool_name=SECRET_TOOL_NAME,
                                   expected_field_name=_secret_field(row.id), expected_project_id=project_id)
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
