"""SessionEnd for a governed client session (``POST sessions/finalize``).

Marks the shadow session completed and turns the client's conversation digest
into platform knowledge through the same path as the external session ingest
(``mcp_external_session.persist_session_knowledge``): knowledge-graph processing
and the work-item link. The transcript lives on the shadow session.

Unlike that ingest, finalize never deletes or replaces what the gateway recorded
during the session (usage events, messages, tool calls): those are the governed
record; the digest only adds knowledge. Summary and digest are re-redacted and
bounded server-side, whatever the client already did.

The knowledge key uses a gateway-owned client session id
(``octryx-claude-<session key>``) so a CLI watcher ingesting the same Claude Code
session under its own ``claude-code-<id>`` never re-ingests (and so never wipes)
the gateway session.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session, UsageEvent
from ...time_utils import utc_now
from ..mcp_external_session import persist_session_knowledge
from ..redaction_policy import redact_secret_text
from .contract import SESSION_KEY_METADATA
from .identity import GatewayIdentity

STATE_FINALIZED = "finalized"
REASON_SESSION_FINALIZED = "session_finalized"

CLIENT_SESSION_PREFIX = "octryx-claude-"
MAX_SUMMARY_CHARS = 8000
MAX_DIGEST_CHARS = 80_000
MAX_REF_CHARS = 300
MAX_MODELS = 20

_GRAPH_COUNTERS = ("chunks_indexed", "graph_entities", "graph_relations")


@dataclass(frozen=True, slots=True)
class FinalizeInput:
    summary: str
    transcript_digest: str
    workspace_ref: str
    claude_session_id: str

    @classmethod
    def from_body(cls, body: dict[str, Any]) -> FinalizeInput:
        def text(key: str, limit: int) -> str:
            value = body.get(key)
            return redact_secret_text(value, max_chars=limit) if isinstance(value, str) else ""

        return cls(
            summary=text("summary", MAX_SUMMARY_CHARS),
            transcript_digest=text("transcript_digest", MAX_DIGEST_CHARS),
            workspace_ref=text("workspace_ref", MAX_REF_CHARS),
            claude_session_id=text("claude_session_id", MAX_REF_CHARS),
        )


def _graph_state(graph: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(graph, dict):
        return None
    state: dict[str, Any] = {key: int(graph.get(key) or 0) for key in _GRAPH_COUNTERS}
    extraction = graph.get("extraction")
    state["extraction"] = extraction if extraction in {"completed", "unavailable", "failed", "skipped"} else "unknown"
    return state


def _work_item_state(work_item_key: str, link: dict[str, Any] | None) -> str:
    if not work_item_key:
        return "not_requested"
    if not isinstance(link, dict):
        return "not_linked"
    if "error" in link:
        return "not_found" if str(link["error"]).startswith("work item not found") else "failed"
    return "linked"


async def _session_models(db: AsyncSession, session_id: str) -> list[str]:
    rows = await db.execute(
        select(UsageEvent.model).where(UsageEvent.session_id == session_id).distinct().limit(MAX_MODELS)
    )
    return [str(model) for model in rows.scalars().all() if model]


async def finalize_gateway_session(
    db: AsyncSession,
    *,
    session: Session,
    identity: GatewayIdentity,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Complete the session and persist its digest as knowledge. Commits."""

    data = FinalizeInput.from_body(body)
    metadata = dict(session.metadata_ or {})
    client_session_id = f"{CLIENT_SESSION_PREFIX}{metadata.get(SESSION_KEY_METADATA) or identity.session_key}"
    work_item_key = identity.work_item_key or str(metadata.get("work_item_key") or "")
    if data.summary:
        metadata["summary"] = data.summary
    metadata.update(
        {
            "client_session_id": client_session_id,
            "claude_session_id": data.claude_session_id or metadata.get("claude_session_id"),
            "workspace_ref": data.workspace_ref or metadata.get("workspace_ref"),
            "finalized_at": utc_now().isoformat(),
        }
    )
    session.metadata_ = metadata
    session.status = "completed"
    session.ended_at = utc_now()
    await db.flush()

    knowledge = await persist_session_knowledge(
        db,
        user=identity.user,
        project_id=identity.workspace_id,
        platform_session_id=session.id,
        client_session_id=client_session_id,
        summary=data.summary,
        digest=data.transcript_digest,
        workspace_ref=data.workspace_ref,
        models=await _session_models(db, session.id),
        work_item_key=work_item_key,
    )
    await db.commit()
    return {
        "state": STATE_FINALIZED,
        "reason": REASON_SESSION_FINALIZED,
        "external_session_id": session.id,
        "knowledge_graph": _graph_state(knowledge["knowledge_graph"]),
        "work_item_link": _work_item_state(work_item_key, knowledge["work_item_link"]),
    }


__all__ = ["CLIENT_SESSION_PREFIX", "STATE_FINALIZED", "FinalizeInput", "finalize_gateway_session"]
