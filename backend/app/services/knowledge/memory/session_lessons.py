"""Lessons learned from octryx sessions, proposed to the team memory. Candidates are stored as ``proposed``, which
recall never includes, until a person confirms them."""

from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.prompt_catalog import render_prompt
from app.services.prompt_catalog.out_of_turn import scoped_prompt_set

from ....models import AuditLog
from ....models.project.knowledge_memory import (
    KnowledgeMemoryItem,
    MemoryAuthorClass,
    MemoryClass,
    MemoryScope,
    MemoryState,
)
from ....time_utils import utc_now
from .capture_model import CaptureModelUnavailableError, governed_capture_model
from .errors import MemoryRefusedError
from .settings import session_lessons_enabled
from .text_guard import content_hash, normalize_memory_text

LESSON_CLASSES = (MemoryClass.DECISION.value, MemoryClass.CONVENTION.value, MemoryClass.LEARNING.value)
MAX_CANDIDATES = 3
MAX_PER_SESSION_DAY = 6
MAX_PER_WORKSPACE_DAY = 30
MAX_FACTS_CHARS = 6000
MAX_SUMMARY_CHARS = 8000
REF = re.compile(r"^[A-Za-z0-9_-]{8,48}$")  # turn_ref holds 64: "lessons:" + ref
TURN_REF_PREFIX = "lessons:"
AUDIT_PROCESSED = "knowledge_memory.lessons_processed"
LESSONS_ANSWER_CONTRACT = (
    'Answer only with JSON: {"lessons": [{"class": "decision" | "convention" | "learning", "text": "..."}]}.'
)

# Secret shapes redacted from every text before it reaches a model (the client does the same before sending).
_SECRETS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|$)", re.S),
    re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"(?i)(aws_secret_access_key|secret_access_key|aws_session_token)\s*[=:]\s*\S+"),
    re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bsk-(ant-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\s*[=:]\s*\S+"),
]


def redact(text: str) -> str:
    for pattern in _SECRETS:
        text = pattern.sub("[redacted]", text)
    return text


def _facts_text(facts: Any) -> str:
    if not isinstance(facts, dict):
        return ""
    parts: list[str] = []
    if isinstance(facts.get("goal"), str):
        parts.append(f"Goal: {facts['goal'][:600]}")
    for label, key in (("Request", "requests"), ("Open todo", "todos")):
        for item in (facts.get(key) or [])[:8] if isinstance(facts.get(key), list) else []:
            if isinstance(item, str):
                parts.append(f"{label}: {item[:600]}")
    files = [item for item in facts.get("files") or [] if isinstance(item, str)][:30] \
        if isinstance(facts.get("files"), list) else []
    if files:
        parts.append("Files changed: " + ", ".join(path[:200] for path in files))
    for test in (facts.get("tests") or [])[:4] if isinstance(facts.get("tests"), list) else []:
        if isinstance(test, dict) and isinstance(test.get("command"), str):
            parts.append(f"Test: `{test['command'][:200]}` {'passed' if test.get('passed') else 'failed'}")
    return redact("\n".join(parts))[:MAX_FACTS_CHARS]


def accepted(reply: Any) -> list[tuple[str, str]]:
    lessons = reply.get("lessons") if isinstance(reply, dict) else None
    out: list[tuple[str, str]] = []
    for item in lessons if isinstance(lessons, list) else []:
        if isinstance(item, dict) and item.get("class") in LESSON_CLASSES and isinstance(item.get("text"), str):
            out.append((item["class"], item["text"]))
        if len(out) >= MAX_CANDIDATES:
            break
    return out


async def _count(db: AsyncSession, *conditions: Any) -> int:
    since = (utc_now() - timedelta(days=1)).replace(tzinfo=None)
    return int(await db.scalar(select(func.count()).select_from(KnowledgeMemoryItem).where(
        KnowledgeMemoryItem.created_at >= since, KnowledgeMemoryItem.turn_ref.like(f"{TURN_REF_PREFIX}%"),
        *conditions)) or 0)


async def _propose(db: AsyncSession, reply: Any, *, allowance: int, user_id: str, workspace_id: str,
                   session_id: str, ref: str) -> tuple[int, int]:
    proposed, skipped = 0, 0
    for item_class, text in accepted(reply):
        if proposed >= allowance:
            skipped += 1
            continue
        if redact(text) != text:  # a candidate that carried a secret is dropped whole, never stored redacted
            skipped += 1
            continue
        try:
            body = normalize_memory_text(text)
        except MemoryRefusedError:  # bounds, characters, or a secret text_guard recognises
            skipped += 1
            continue
        digest = content_hash(body)
        known = await db.scalar(select(func.count()).select_from(KnowledgeMemoryItem).where(
            KnowledgeMemoryItem.project_id == workspace_id, KnowledgeMemoryItem.content_hash == digest))
        if known:
            skipped += 1
            continue
        db.add(KnowledgeMemoryItem(
            project_id=workspace_id, scope=MemoryScope.WORKSPACE.value, item_class=item_class,
            author_class=MemoryAuthorClass.MODEL_INFERRED.value, state=MemoryState.PROPOSED.value, text=body,
            content_hash=digest, session_id=session_id, turn_ref=f"{TURN_REF_PREFIX}{ref}", author_user_id=user_id,
            created_at=utc_now()))
        await db.flush()
        proposed += 1
    return proposed, skipped


async def capture_session_lessons(db: AsyncSession, *, user_id: str, workspace_id: str, session_id: str, ref: Any,
                                  facts: Any, summary: Any, model_factory: Any = None) -> dict:
    if not await session_lessons_enabled(db, workspace_id):
        return {"state": "off"}
    if not isinstance(ref, str) or not REF.match(ref):
        return {"state": "invalid", "reason": "ref_invalid"}
    marker = f"{session_id}:{ref}"[:120]
    processed = await db.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.action == AUDIT_PROCESSED, AuditLog.resource_id == marker))
    if processed:
        return {"state": "duplicate"}
    # What is left of the day's allowance caps this call too: never above 6 / 30, not even by one call.
    allowance = min(MAX_PER_SESSION_DAY - await _count(db, KnowledgeMemoryItem.session_id == session_id),
                    MAX_PER_WORKSPACE_DAY - await _count(db, KnowledgeMemoryItem.project_id == workspace_id))
    if allowance <= 0:
        return {"state": "limited"}
    facts_text = _facts_text(facts)
    summary_text = redact(summary)[:MAX_SUMMARY_CHARS] if isinstance(summary, str) and summary.strip() else ""
    if not facts_text and not summary_text:
        return {"state": "nothing_to_capture"}
    db.add(AuditLog(user_id=user_id, action=AUDIT_PROCESSED, resource_type="session_lessons", resource_id=marker,
                    project_id=workspace_id,
                    details={"session_id": session_id}))
    try:
        async with scoped_prompt_set(db, workspace_id=workspace_id):
            system = render_prompt("knowledge.memory.lessons_system", answer_contract=LESSONS_ANSWER_CONTRACT)
            message = render_prompt("knowledge.memory.lessons_session", facts=facts_text or "(none)",
                                    summary=summary_text or "(none)")
        model = await (model_factory or governed_capture_model)(db, project_id=workspace_id)
        reply = await model.json(system=system, user=message)
    except CaptureModelUnavailableError as error:
        await db.flush()
        return {"state": "model_unavailable", "reason": str(error.state)}
    except (ValueError, json.JSONDecodeError):
        await db.flush()
        return {"state": "nothing_to_capture"}
    proposed, skipped = await _propose(db, reply, allowance=allowance, user_id=user_id, workspace_id=workspace_id,
                                       session_id=session_id, ref=ref)
    await db.flush()
    return {"state": "captured" if proposed else "nothing_to_capture", "proposed": proposed, "skipped": skipped}


__all__ = ["LESSON_CLASSES", "accepted", "capture_session_lessons", "redact"]
