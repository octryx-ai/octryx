"""A handoff's durable lessons become Workspace memory.

On a confirmed takeover, and when a Work Item reaches a done state, the latest handoff's ``open_decisions``
(class ``decision``), ``pitfalls`` (``learning``) and ``rules`` (``convention``) are written through the existing
memory service (``knowledge/memory/capture.remember``), so ``memory_recall`` finds them:

- one item per Work Item and section, keyed by ``turn_ref = handoff:<work item id>:<section>``; a changed section
  supersedes the previous item of that key (``supersedes_id``, the old one ``superseded``);
- the author class is ``model_inferred`` for an agent's handoff and ``human_stated`` for a person's;
- idempotent: the same content again records nothing new (``remember`` consolidates by content).

Texts were secret-scanned when the handoff was written; the memory service scans them again.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkItem, WorkItemHandoff
from ...models.project.knowledge_memory import (
    MAX_MEMORY_TEXT_CHARS,
    KnowledgeMemoryItem,
    MemoryAuthorClass,
    MemoryState,
)
from ...time_utils import utc_now
from ..knowledge.access.authorization import AuthorizedWorkspace
from ..knowledge.identity.workspace import WorkspaceId
from ..knowledge.memory.capture import MemoryProvenance, remember
from ..knowledge.memory.errors import MemoryRefusedError
from ..knowledge.memory.visibility import recallable
from .handoffs import AUTHOR_AGENT, latest_handoff

logger = logging.getLogger(__name__)

SECTION_CLASSES = {"open_decisions": "decision", "pitfalls": "learning", "rules": "convention"}
SECTION_LABELS = {"open_decisions": "open decisions", "pitfalls": "pitfalls", "rules": "rules"}
DONE_STATES = frozenset({"done", "completed"})


def memory_key(work_item_id: str, section: str) -> str:
    return f"handoff:{work_item_id}:{section}"


def _text(item: WorkItem, section: str, value: object) -> str:
    entries = [value] if isinstance(value, str) else [entry for entry in value or [] if isinstance(entry, str)]
    body = "; ".join(entry.strip() for entry in entries if entry.strip())
    if not body:
        return ""
    text = f"{item.source_key} {SECTION_LABELS[section]}: {body}"
    return text if len(text) <= MAX_MEMORY_TEXT_CHARS else text[: MAX_MEMORY_TEXT_CHARS - 1] + "…"


async def _previous(db: AsyncSession, project_id: str, key: str) -> KnowledgeMemoryItem | None:
    statement = (
        select(KnowledgeMemoryItem)
        .where(KnowledgeMemoryItem.project_id == project_id, KnowledgeMemoryItem.turn_ref == key,
               recallable(utc_now()))
        .order_by(KnowledgeMemoryItem.created_at.desc())
        .limit(1)
    )
    return (await db.execute(statement)).scalar_one_or_none()


async def capture_handoff_memory(db: AsyncSession, handoff: WorkItemHandoff) -> list[str]:
    """Write the handoff's lessons; returns the outcomes per section (``recorded``/``already_known``...). Flushes."""
    item = await db.get(WorkItem, handoff.work_item_id)
    try:
        workspace = WorkspaceId.parse(handoff.project_id)
    except Exception:  # noqa: BLE001 - a Workspace the knowledge layer cannot address has no memory
        logger.info("Handoff memory skipped: Workspace id is not addressable")
        return []
    authorized = AuthorizedWorkspace(workspace=workspace, project_id=handoff.project_id, role="admin")
    author_class = (MemoryAuthorClass.MODEL_INFERRED if handoff.author_kind == AUTHOR_AGENT
                    else MemoryAuthorClass.HUMAN_STATED)
    outcomes: list[str] = []
    sections = dict(handoff.sections or {})
    for section, item_class in SECTION_CLASSES.items():
        text = _text(item, section, sections.get(section)) if item is not None else ""
        if not text:
            continue
        key = memory_key(handoff.work_item_id, section)
        previous = await _previous(db, handoff.project_id, key)
        try:
            result = await remember(
                db, authorized=authorized,
                provenance=MemoryProvenance(user_id=handoff.author_user_id, session_id=handoff.id, turn_ref=key),
                text=text, scope="workspace", item_class=item_class, author_class=author_class,
            )
        except MemoryRefusedError as error:
            logger.info("Handoff memory refused for one section: %s", error.reason)
            outcomes.append("refused")
            continue
        if previous is not None and result.item.id != previous.id and result.outcome == "recorded":
            result.item.supersedes_id = previous.id
            previous.state = MemoryState.SUPERSEDED.value
            previous.state_changed_by = handoff.author_user_id
            previous.state_changed_at = utc_now()
        outcomes.append(result.outcome)
    await db.flush()
    return outcomes


async def capture_latest_handoff_memory(db: AsyncSession, work_item_id: str) -> list[str]:
    handoff = await latest_handoff(db, work_item_id)
    return await capture_handoff_memory(db, handoff) if handoff is not None else []


async def capture_if_done(db: AsyncSession, work_item_id: str) -> list[str]:
    """After a transition: a Work Item in a done state keeps its latest handoff's lessons."""
    item = await db.get(WorkItem, work_item_id)
    if item is None:
        return []
    await db.refresh(item)
    if str(item.work_state or "").lower() not in DONE_STATES:
        return []
    return await capture_latest_handoff_memory(db, work_item_id)


__all__ = [
    "DONE_STATES",
    "SECTION_CLASSES",
    "capture_handoff_memory",
    "capture_if_done",
    "capture_latest_handoff_memory",
    "memory_key",
]
