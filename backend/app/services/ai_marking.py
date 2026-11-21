"""Marking of AI-written output (EU AI Act Art. 50(2)).

Server-side agent writes to git and external systems carry a machine-readable mark: git commits get trailers, pull
request descriptions and Jira/Confluence bodies get a visible marker line, Confluence pages also the label
``ai-generated``. The model comes from the turn's runtime; nothing is marked when the model is unknown (never invent
one). All helpers are idempotent so retries and re-publishes never stack markers.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

CONFLUENCE_LABEL = "ai-generated"
COMMIT_TRAILER = "AI-Generated-By-octryx"
RUN_TRAILER = "Octryx-Run"
MARKER_PREFIX = "Written by AI (octryx"

_TRAILER_LINE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*: \S")


@dataclass(frozen=True)
class MarkingFacts:
    model: str
    run_key: str | None


async def _run_key(db: Any, session_id: str | None) -> str | None:
    from ..models.runtime.secure_work import WorkItem
    from .workflow_runs.records import active_run_for_session

    run = await active_run_for_session(db, session_id)
    work_item_id = getattr(run, "work_item_id", None) if run is not None else None
    if not work_item_id:
        return None
    item = await db.get(WorkItem, work_item_id)
    key = str(getattr(item, "source_key", "") or "").strip() if item is not None else ""
    return key or None


async def marking_facts(context: Any) -> MarkingFacts | None:
    """The facts to mark this turn's output with, or ``None`` when the model is unknown. Never raises."""
    model = str(getattr(context, "turn_model", None) or "").strip() if context is not None else ""
    if not model:
        return None
    run_key = None
    db = getattr(context, "db", None)
    if db is not None:
        try:
            run_key = await _run_key(db, getattr(context, "session_id", None))
        except Exception:  # noqa: BLE001 - marking must never fail the write
            logger.debug("ai marking: run key lookup failed", exc_info=True)
            run_key = None
    return MarkingFacts(model=model, run_key=run_key)


async def run_marking_facts(db: Any, run: Any) -> MarkingFacts | None:
    """Facts for platform writes of a workflow run (no agent turn): the model of the latest assistant answer in the
    run's main session and the run's Work item key. ``None`` when no model is recorded. Never raises."""
    try:
        from sqlalchemy import select

        from ..models.runtime.secure_work import WorkItem
        from ..models.session.session import Message
        from .workflow_runs.records import main_session_id

        session_id = await main_session_id(db, run)
        if not session_id:
            return None
        model = (await db.execute(
            select(Message.model)
            .where(Message.session_id == session_id, Message.role == "assistant", Message.model.isnot(None),
                   Message.model != "")
            .order_by(Message.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        model = str(model or "").strip()
        # A device answer is stored as "device:<...>", which names no model.
        if not model or model.startswith("device:"):
            return None
        item = await db.get(WorkItem, run.work_item_id) if getattr(run, "work_item_id", None) else None
        run_key = str(getattr(item, "source_key", "") or "").strip() or str(getattr(run, "ticket_key", "") or "")
        return MarkingFacts(model=model, run_key=run_key.strip() or None)
    except Exception:  # noqa: BLE001 - marking must never fail the write
        logger.debug("ai marking: run facts lookup failed", exc_info=True)
        return None


def facts_to_dict(facts: MarkingFacts | None) -> dict[str, Any] | None:
    return {"model": facts.model, "run_key": facts.run_key} if facts is not None else None


def facts_from_dict(raw: Any) -> MarkingFacts | None:
    if not isinstance(raw, dict) or not str(raw.get("model") or "").strip():
        return None
    run_key = str(raw.get("run_key") or "").strip()
    return MarkingFacts(model=str(raw["model"]).strip(), run_key=run_key or None)


def _is_trailer_block(paragraph: str) -> bool:
    lines = [line for line in paragraph.splitlines() if line.strip()]
    return bool(lines) and all(_TRAILER_LINE.match(line) for line in lines)


def commit_message_with_trailers(message: str, facts: MarkingFacts | None) -> str:
    """Append the AI trailers to a commit message (git trailer convention); unchanged without facts or if marked."""
    if facts is None or f"{COMMIT_TRAILER}:" in (message or ""):
        return message
    trailers = [f"{COMMIT_TRAILER}: {facts.model}"]
    if facts.run_key:
        trailers.append(f"{RUN_TRAILER}: {facts.run_key}")
    body = (message or "").rstrip()
    if not body:
        return "\n".join(trailers)
    paragraphs = re.split(r"\n\s*\n", body)
    # A one-paragraph message is the subject line; never treat it as a trailer block.
    separator = "\n" if len(paragraphs) > 1 and _is_trailer_block(paragraphs[-1]) else "\n\n"
    return body + separator + "\n".join(trailers)


def marker_line(facts: MarkingFacts) -> str:
    run = f" in run {facts.run_key}" if facts.run_key else ""
    return f"— {MARKER_PREFIX} · {facts.model}){run}."


def with_marker(text: str, facts: MarkingFacts | None) -> str:
    """Append the marker line to a Markdown/plain body (PR description, comment); idempotent."""
    if facts is None or MARKER_PREFIX in (text or ""):
        return text
    body = (text or "").rstrip()
    return f"{body}\n\n{marker_line(facts)}" if body else marker_line(facts)


def storage_marker(facts: MarkingFacts) -> str:
    return f"<p><em>{html.escape(marker_line(facts))}</em></p>"


def with_storage_marker(storage_html: str, facts: MarkingFacts | None) -> str:
    """Append the marker paragraph to Confluence storage format; idempotent."""
    if facts is None or MARKER_PREFIX in (storage_html or ""):
        return storage_html
    return f"{storage_html or ''}{storage_marker(facts)}"
