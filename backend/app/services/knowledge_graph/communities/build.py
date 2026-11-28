"""(Re)build the community rows of one scope."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.error_facts import error_text
from app.services.prompt_catalog import prompt_set_scope
from app.services.prompt_catalog.out_of_turn import prompt_set_for

from ....models import KnowledgeCommunity, KnowledgeGraphEdge, KnowledgeGraphNode
from ....time_utils import utc_now
from ...knowledge_embedding import EmbeddingConfigurationError, resolve_knowledge_embedding_runtime
from .detection import _community_key, _structural_summary, detect_communities
from .reports import GenerateFn, _parse_report, build_report_prompt

# The package name keeps the log records under the communities logger.
logger = logging.getLogger(__package__)


async def _scope_graph(db: AsyncSession, project_id: str | None) -> tuple[list[Any], list[Any]]:
    node_stmt = select(KnowledgeGraphNode).where(KnowledgeGraphNode.status == "active")
    edge_stmt = select(KnowledgeGraphEdge).where(KnowledgeGraphEdge.status == "active")
    if project_id is not None:
        node_stmt = node_stmt.where(
            or_(KnowledgeGraphNode.project_id == project_id, KnowledgeGraphNode.project_id.is_(None))
        )
        edge_stmt = edge_stmt.where(
            or_(KnowledgeGraphEdge.project_id == project_id, KnowledgeGraphEdge.project_id.is_(None))
        )
    nodes = list((await db.execute(node_stmt)).scalars().all())
    edges = list((await db.execute(edge_stmt)).scalars().all())
    return nodes, edges


async def _cluster_report(
    members: list[Any], edges: list[Any], generate: GenerateFn | None, prompts: Any
) -> tuple[str, str, str, bool]:
    title = ""
    summary = _structural_summary(members, edges)
    summary_source = "deterministic"
    reported = False
    if generate is not None:
        try:
            with prompt_set_scope(prompts):
                report_prompt = build_report_prompt(members, edges)
            parsed = _parse_report(await generate(report_prompt))
            if parsed is not None:
                title, summary = parsed
                summary_source = "llm"
                reported = True
        except Exception as exc:  # noqa: BLE001 - keep the structural summary
            logger.warning(
                "Community report generation failed; keeping structural summary: %s",
                error_text("community_report_failed", exc),
            )
    if not title:
        top = sorted(members, key=lambda item: item.display_name)[:3]
        title = " / ".join(node.display_name for node in top)
    return title, summary, summary_source, reported


def _write_row(
    db: AsyncSession,
    existing: dict[str, Any],
    *,
    key: str,
    cluster: list[str],
    project_id: str | None,
    scope: str,
    report: tuple[str, str, str, bool],
) -> tuple[Any, bool]:
    title, summary, summary_source, _ = report
    row = existing.get(key)
    if row is None:
        row = KnowledgeCommunity(
            id=str(uuid.uuid4()),
            project_id=project_id,
            project_scope=scope,
            community_key=key,
            title=title,
            summary=summary,
            summary_source=summary_source,
            member_node_ids=cluster,
            size=len(cluster),
        )
        db.add(row)
        return row, True
    row.title = title
    row.summary = summary
    row.summary_source = summary_source
    row.member_node_ids = cluster
    row.size = len(cluster)
    row.status = "active"
    return row, False


async def _embed_row(db: AsyncSession, row: Any) -> None:
    try:
        provider = await resolve_knowledge_embedding_runtime(db)
        row.embedding = provider.embed_text(f"{row.title}. {row.summary}")
        row.embedding_provider = provider.provider_id
        row.embedding_model = provider.model
        row.embedding_version = provider.version
        row.embedding_updated_at = utc_now()
    except EmbeddingConfigurationError as exc:
        logger.warning("Community embedding unavailable: %s", exc)


def _retire_unseen(existing: dict[str, Any], seen_keys: set[str]) -> int:
    retired = 0
    for key, row in existing.items():
        if key not in seen_keys and row.status == "active":
            row.status = "retired"
            retired += 1
    return retired


async def build_communities(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    generate: GenerateFn | None = None,
) -> dict[str, Any]:
    """(Re)build the community layer for a scope. Existing communities for the
    scope are replaced (stale clusters retire as the graph evolves)."""
    scope = project_id or ""
    nodes, edges = await _scope_graph(db, project_id)
    node_by_id = {node.id: node for node in nodes}

    clusters = detect_communities(nodes, edges)

    existing = {
        row.community_key: row
        for row in (
            await db.execute(select(KnowledgeCommunity).where(KnowledgeCommunity.project_scope == scope))
        ).scalars().all()
    }
    seen_keys: set[str] = set()
    created = updated = reported = 0
    prompts = await prompt_set_for(db, workspace_id=project_id) if generate is not None else None

    for cluster in clusters:
        members = [node_by_id[nid] for nid in cluster if nid in node_by_id]
        if len(members) < 2:
            continue
        key = _community_key(cluster)
        seen_keys.add(key)

        report = await _cluster_report(members, edges, generate, prompts)
        reported += int(report[3])
        row, was_created = _write_row(
            db, existing, key=key, cluster=cluster, project_id=project_id, scope=scope, report=report
        )
        if was_created:
            created += 1
        else:
            updated += 1
        await _embed_row(db, row)

    retired = _retire_unseen(existing, seen_keys)

    await db.flush()
    return {
        "communities": len(seen_keys),
        "created": created,
        "updated": updated,
        "retired": retired,
        "llm_reports": reported,
    }
