"""Agent sessions become knowledge-graph fuel at ingest time.

External CLI sessions (Claude Code, Codex, OpenCode, ...) arrive through
``session_ingest`` outside the connector sync pipeline, so the graph stage
never sees them. This module gives them the same treatment inline on ingest:

1. Chunk indexing — the session digest becomes retrievable passages.
2. Deterministic record — the session node, the person who ran it, and the
   workspace it touched become alias-resolved graph nodes and edges.
3. Governed LLM extraction (best effort) — entities/relations mentioned in
   the conversation flow into the graph via the EXTRACT runtime; when no
   runtime is configured the step reports itself as unavailable instead of
   degrading silently.

A session is referenced as ``agent-session:<platform session id>`` (its shadow
session).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ..error_facts import error_text
from ..knowledge_chunking import index_source_chunks
from .extractors import ingest_person_from_source
from .extractors.prose import extract_graph_from_text
from .llm_runtime import ROLE_EXTRACT, KnowledgeLLMUnavailableError, build_generate_fn
from .store import resolve_node_by_alias, upsert_edge, upsert_node

logger = logging.getLogger(__name__)

_MAX_EXTRACTION_CHARS = 12_000


@dataclass(frozen=True, slots=True)
class AgentSessionRecord:
    """One ingested external session: its shadow session, stable key, and redacted text."""

    session_id: str
    key: str
    title: str
    summary: str = ""
    content: str = ""
    tags: tuple[str, ...] = field(default=("agent-session",))

    @property
    def source_ref(self) -> str:
        return f"agent-session:{self.session_id}"


def _session_text(record: AgentSessionRecord) -> str:
    parts = [record.summary, record.content]
    return "\n\n".join(part for part in parts if part.strip()).strip()


async def _link_person(
    db: AsyncSession, *, project_id: str, user: User, session_node: Any, source_ref: str
) -> None:
    person_node = await ingest_person_from_source(
        db,
        project_id=project_id,
        person={
            "display_name": user.display_name or user.username,
            "username": user.username,
            "email": user.email,
        },
        source_ref=source_ref,
    )
    if person_node is not None:
        await upsert_edge(
            db,
            project_id=project_id,
            edge_type="contributed_to",
            source_node_id=person_node.id,
            target_node_id=session_node.id,
            description=f"{person_node.display_name} ran {session_node.display_name}",
            source_refs=[source_ref],
        )


async def _link_workspace(
    db: AsyncSession, *, project_id: str, workspace_ref: str, session_node: Any, source_ref: str
) -> None:
    workspace_name = PurePosixPath(str(workspace_ref or "").rstrip("/")).name
    if workspace_name:
        workspace_node = await resolve_node_by_alias(
            db, project_id=project_id, alias=workspace_name
        ) or await resolve_node_by_alias(db, project_id=None, alias=workspace_name)
        # A workspace is a checkout: only link nodes that ARE a codebase.
        # Alias collisions (e.g. a Terraform stack also named after the repo)
        # must not produce a misleading "worked in" edge.
        if workspace_node is not None and workspace_node.node_type not in {"repository", "system"}:
            workspace_node = None
        if workspace_node is not None:
            await upsert_edge(
                db,
                project_id=project_id,
                edge_type="references",
                source_node_id=session_node.id,
                target_node_id=workspace_node.id,
                description=f"{session_node.display_name} worked in {workspace_node.display_name}",
                source_refs=[source_ref],
            )


async def ingest_agent_session_record(
    db: AsyncSession,
    *,
    project_id: str,
    record: AgentSessionRecord,
    user: User,
    workspace_ref: str = "",
    models: list[str] | None = None,
) -> Any:
    """Deterministic session record: session node + person + workspace edges."""
    source_ref = record.source_ref
    session_node = await upsert_node(
        db,
        project_id=project_id,
        node_type="agent_session",
        node_key=record.key,
        display_name=record.title or record.key,
        description=record.summary[:800],
        properties={
            key: item
            for key, item in {"workspace_ref": workspace_ref, "models": list(models or [])}.items()
            if item
        },
        source_refs=[source_ref],
        # Session keys are globally unique; generic display names must not
        # merge different sessions via alias resolution.
        resolve_by_alias=False,
    )
    await _link_person(db, project_id=project_id, user=user, session_node=session_node, source_ref=source_ref)
    await _link_workspace(
        db, project_id=project_id, workspace_ref=workspace_ref, session_node=session_node, source_ref=source_ref
    )
    return session_node


async def _index_chunks(
    db: AsyncSession, *, project_id: str, record: AgentSessionRecord, text: str, result: dict[str, Any]
) -> None:
    try:
        chunks = await index_source_chunks(
            db,
            project_id=project_id,
            source_ref=record.source_ref,
            text=text,
            source_kind="agent_session",
            tags=list(record.tags),
        )
        result["chunks_indexed"] = int(chunks.get("created") or 0) + int(chunks.get("updated") or 0)
        if chunks.get("embed_error"):
            result["errors"].append(f"chunk embed: {chunks['embed_error']}")
    except Exception as exc:  # noqa: BLE001 - chunking must not sink the ingest
        result["errors"].append(f"chunks: {error_text('agent_session_chunking_failed', exc)}")
        logger.exception("agent_session_graph.chunk_failed", extra={"session_id": record.session_id})


async def _extract_entities(
    db: AsyncSession, *, project_id: str, record: AgentSessionRecord, text: str, result: dict[str, Any]
) -> None:
    try:
        generate = await build_generate_fn(db, project_ids=project_id, role=ROLE_EXTRACT)
    except KnowledgeLLMUnavailableError as exc:
        result["extraction"] = "unavailable"
        result["errors"].append(f"extraction unavailable: {exc}")
        return
    try:
        # One pass without gleaning: sessions arrive daily, and the digest is
        # already a distillation — recall rounds don't justify doubled cost.
        extraction = await extract_graph_from_text(
            db,
            project_id=project_id,
            text=text[:_MAX_EXTRACTION_CHARS],
            source_ref=record.source_ref,
            generate=generate,
            gleaning_rounds=0,
        )
        result["graph_entities"] += int(extraction.get("entities") or 0)
        result["graph_relations"] += int(extraction.get("relations") or 0)
        result["extraction"] = "completed"
    except Exception as exc:  # noqa: BLE001
        result["extraction"] = "failed"
        result["errors"].append(f"extraction: {error_text('agent_session_extraction_failed', exc)}")
        logger.exception("agent_session_graph.extract_failed", extra={"session_id": record.session_id})


async def process_agent_session_knowledge(
    db: AsyncSession,
    *,
    project_id: str,
    record: AgentSessionRecord,
    user: User,
    workspace_ref: str = "",
    models: list[str] | None = None,
) -> dict[str, Any]:
    """Run the full ingest-time graph treatment for one ingested session."""
    result: dict[str, Any] = {
        "chunks_indexed": 0,
        "graph_entities": 0,
        "graph_relations": 0,
        "extraction": "skipped",
        "errors": [],
    }
    text = _session_text(record)
    if not text:
        return result

    await _index_chunks(db, project_id=project_id, record=record, text=text, result=result)

    try:
        await ingest_agent_session_record(
            db,
            project_id=project_id,
            record=record,
            user=user,
            workspace_ref=workspace_ref,
            models=models,
        )
        result["graph_entities"] += 1
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"record: {error_text('agent_session_record_failed', exc)}")
        logger.exception("agent_session_graph.record_failed", extra={"session_id": record.session_id})

    await _extract_entities(db, project_id=project_id, record=record, text=text, result=result)
    return result


__all__ = ["AgentSessionRecord", "ingest_agent_session_record", "process_agent_session_knowledge"]
