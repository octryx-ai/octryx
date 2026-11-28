"""Replace or remove the own Git token of a repository source. A new token is checked against exactly that repository
first."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .....models.project.knowledge_source_sync import CONNECTOR_KIND_GIT_REPOSITORY, KnowledgeSourceConnector
from ...access.authorization import AuthorizedWorkspace
from ...ledger.errors import EvidenceLedgerContractError
from ..repository_git_token import check_git_token, remove_git_token, source_repository, store_git_token
from .contract import REASON_GIT_TOKEN_NOT_SUPPORTED, ConnectorError


def _repository(authorized: AuthorizedWorkspace, row: KnowledgeSourceConnector):
    if type(authorized) is not AuthorizedWorkspace or not authorized.may_author:
        raise EvidenceLedgerContractError()
    repository = source_repository(row.scope) if row.kind == CONNECTOR_KIND_GIT_REPOSITORY else None
    if repository is None or not row.connection_id:
        raise ConnectorError(REASON_GIT_TOKEN_NOT_SUPPORTED)
    return repository


async def replace_git_token(
    db: AsyncSession, *, authorized: AuthorizedWorkspace, row: KnowledgeSourceConnector, git_token: object,
    actor_id: str,
) -> KnowledgeSourceConnector:
    checked = await check_git_token(_repository(authorized, row), git_token)
    await store_git_token(db, connector=row, checked=checked, actor_id=actor_id)
    await db.commit()
    return row


async def clear_git_token(
    db: AsyncSession, *, authorized: AuthorizedWorkspace, row: KnowledgeSourceConnector, actor_id: str
) -> KnowledgeSourceConnector:
    _repository(authorized, row)
    if await remove_git_token(db, connector=row, actor_id=actor_id):
        await db.commit()
    return row


__all__ = ["clear_git_token", "replace_git_token"]
