"""Marking of agent-written output (EU AI Act Art. 50(2); anti-slop E). Everything the platform sends out for an agent
names the agent and the person responsible for it."""

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
MARKER_PREFIX = "Written by an agent"

_TRAILER_LINE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*: \S")


@dataclass(frozen=True)
class MarkingFacts:
    responsible: str
    model: str | None = None
    run_key: str | None = None


async def _run_key(db: Any, run: Any) -> str | None:
    from ..models.runtime.secure_work import WorkItem

    item = await db.get(WorkItem, run.work_item_id) if getattr(run, "work_item_id", None) else None
    key = str(getattr(item, "source_key", "") or "").strip() or str(getattr(run, "ticket_key", "") or "").strip()
    return key or None


async def _last_model(db: Any, run: Any) -> str | None:
    from sqlalchemy import select

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
    return None if not model or model.startswith("device:") else model


# A tool's outgoing text names the run's responsible person, else the calling user.
async def marking_facts(context: Any) -> MarkingFacts | None:
    from .ai_marking_responsible import responsible_name
    from .workflow_runs.records import active_run_for_session

    db = getattr(context, "db", None) if context is not None else None
    if db is None:  # a commit still names the model (trailers); the text line needs a person
        model = str(getattr(context, "turn_model", None) or "").strip() if context is not None else ""
        return MarkingFacts(responsible="", model=model) if model else None
    try:
        run = await active_run_for_session(db, getattr(context, "session_id", None))
        if run is not None:
            return await run_marking_facts(db, run, model=getattr(context, "turn_model", None))
        name = await responsible_name(db, user_id=getattr(context, "user_id", None))
    except Exception:  # noqa: BLE001 - marking must never fail the write
        logger.debug("ai marking: responsible lookup failed", exc_info=True)
        return None
    model = str(getattr(context, "turn_model", None) or "").strip() or None
    return MarkingFacts(responsible=name, model=model) if name else None


async def run_marking_facts(db: Any, run: Any, *, model: str | None = None) -> MarkingFacts | None:
    from .ai_marking_responsible import responsible_name

    try:
        name = await responsible_name(db, run=run)
        if not name:
            return None
        return MarkingFacts(responsible=name, model=(str(model or "").strip() or await _last_model(db, run)),
                            run_key=await _run_key(db, run))
    except Exception:  # noqa: BLE001 - marking must never fail the write
        logger.debug("ai marking: run facts lookup failed", exc_info=True)
        return None


def facts_to_dict(facts: MarkingFacts | None) -> dict[str, Any] | None:
    return ({"responsible": facts.responsible, "model": facts.model, "run_key": facts.run_key}
            if facts is not None else None)


def facts_from_dict(raw: Any) -> MarkingFacts | None:
    if not isinstance(raw, dict) or not str(raw.get("responsible") or "").strip():
        return None
    model, run_key = str(raw.get("model") or "").strip(), str(raw.get("run_key") or "").strip()
    return MarkingFacts(responsible=str(raw["responsible"]).strip(), model=model or None, run_key=run_key or None)


def _is_trailer_block(paragraph: str) -> bool:
    lines = [line for line in paragraph.splitlines() if line.strip()]
    return bool(lines) and all(_TRAILER_LINE.match(line) for line in lines)


def commit_message_with_trailers(message: str, facts: MarkingFacts | None) -> str:
    if facts is None or not facts.model or f"{COMMIT_TRAILER}:" in (message or ""):
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
    details = ", ".join(part for part in (f"octryx · {facts.model}" if facts.model else "octryx",
                                          f"run {facts.run_key}" if facts.run_key else "") if part)
    return f"— {MARKER_PREFIX} ({details}) — responsible: {facts.responsible}."


def with_marker(text: str, facts: MarkingFacts | None) -> str:
    if facts is None or not facts.responsible or MARKER_PREFIX in (text or ""):
        return text
    body = (text or "").rstrip()
    return f"{body}\n\n{marker_line(facts)}" if body else marker_line(facts)


def storage_marker(facts: MarkingFacts) -> str:
    return f"<p><em>{html.escape(marker_line(facts))}</em></p>"


def with_storage_marker(storage_html: str, facts: MarkingFacts | None) -> str:
    if facts is None or not facts.responsible or MARKER_PREFIX in (storage_html or ""):
        return storage_html
    return f"{storage_html or ''}{storage_marker(facts)}"


# The arguments without their marker lines, and each field's line, for checks against what a person confirmed.
def without_markers(params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    clean, lines = dict(params), {}
    for key, value in params.items():
        at = value.rfind(f"— {MARKER_PREFIX}") if isinstance(value, str) else -1
        if at >= 0:
            lines[key] = value[at:]
            clean[key] = value[:at].rstrip()
            if not clean[key]:  # the line alone: the agent sent no text of its own here
                del clean[key]
    return clean, lines


def with_markers(params: dict[str, Any], lines: dict[str, str]) -> dict[str, Any]:
    marked = dict(params)
    for key, line in lines.items():
        body = str(marked.get(key) or "").rstrip()
        marked[key] = f"{body}\n\n{line}" if body else line
    return marked
