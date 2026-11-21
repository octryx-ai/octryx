"""Authorized repository metadata for dynamic context, without loading source content."""

from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import KnowledgeCodeFile, KnowledgeEvidenceSource, KnowledgeSourceConnector
from ...prompt_catalog import render_prompt
from ..ledger.errors import EvidenceLedgerError
from ..sources.sync.git_hosts import parse_repository_url
from .authorization import authorize_tool_workspace
from .source_acl import visible_source

MAX_REPOSITORIES = 8


async def authorized_repository_inventory(
    db: AsyncSession, *, user_id: str, workspace_id: str | None, allowed_project_ids: list[str],
) -> list[dict[str, str]]:
    if not workspace_id:
        return []
    try:
        authorized = await authorize_tool_workspace(
            db, user_id=user_id, project_id=workspace_id, allowed_project_ids=allowed_project_ids,
        )
    except EvidenceLedgerError:
        return []
    visible_connectors = select(KnowledgeCodeFile.connector_id).join(
        KnowledgeEvidenceSource, KnowledgeEvidenceSource.id == KnowledgeCodeFile.source_id,
    ).where(
        KnowledgeCodeFile.project_id == authorized.project_id,
        KnowledgeEvidenceSource.project_id == authorized.project_id,
        visible_source(authorized.project_id, KnowledgeEvidenceSource.source_key, authorized.principal_keys),
    )
    rows = (await db.execute(select(KnowledgeSourceConnector).where(
        KnowledgeSourceConnector.project_id == authorized.project_id,
        KnowledgeSourceConnector.kind == "git_repository",
        KnowledgeSourceConnector.state == "active",
        KnowledgeSourceConnector.id.in_(visible_connectors),
    ).order_by(KnowledgeSourceConnector.connector_key).limit(MAX_REPOSITORIES))).scalars().all()
    inventory = []
    for row in rows:
        scope = row.scope or {}
        commit = scope.get("head_commit")
        remote = scope.get("remote")
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            continue
        try:
            parse_repository_url(remote, known_host_only=False)
        except EvidenceLedgerError:
            continue
        inventory.append({"repository": row.connector_key, "remote": remote, "commit": commit})
    return inventory


async def build_repository_source_context(
    db: AsyncSession, *, user_id: str, workspace_id: str | None, allowed_project_ids: list[str],
) -> str:
    inventory = await authorized_repository_inventory(
        db, user_id=user_id, workspace_id=workspace_id, allowed_project_ids=allowed_project_ids,
    )
    if not inventory:
        return ""
    return render_prompt("context.knowledge.repository_sources", inventory=json.dumps(inventory, ensure_ascii=True))
