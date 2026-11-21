""""What did this turn get?": a session's recorded turn next to the dry run of the same inputs.

The latest turn trace of the session records every prompt key it rendered as
``key@version`` (``prompt_templates.used``) and its frozen execution profile. The dry run
prepares the same (Workspace, agent, workflow) again and resolves the catalog under the
same scope, so every key the turn rendered (in preparation or later in its loop) is
compared with the version a turn would render now:

- ``same``: the key renders at the version the turn used;
- ``changed``: it renders at another version now (an override was published or reverted);
- ``setup_only``: preparation renders it now, the turn did not (a different path).

The setups match when no key changed.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.execution_profile_trace import TRACE_EXECUTION_PROFILE_KEY

from ...models import Session
from ...models.runtime.audit import TurnTrace
from ..prompt_catalog import PROMPT_TEMPLATES_TRACE_KEY
from .dry_run import prompt_identity


async def latest_turn_record(db: AsyncSession, session_id: str) -> dict[str, Any] | None:
    trace = (
        await db.execute(
            select(TurnTrace)
            .where(TurnTrace.session_id == session_id)
            .order_by(TurnTrace.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if trace is None:
        return None
    snapshot = trace.context_snapshot_json if isinstance(trace.context_snapshot_json, dict) else {}
    record = snapshot.get(PROMPT_TEMPLATES_TRACE_KEY)
    record = record if isinstance(record, dict) else {}
    used = record.get("used") if isinstance(record.get("used"), dict) else {}
    return {
        "trace_id": trace.id,
        "created_at": trace.created_at.isoformat() if trace.created_at else None,
        "prompt_refs": {key: prompt_identity(entry) for key, entry in used.items() if isinstance(entry, dict)},
        "execution_profile": dict(snapshot.get(TRACE_EXECUTION_PROFILE_KEY) or {}),
    }


def session_setup_inputs(session: Session) -> dict[str, str]:
    """The inputs a turn of ``session`` was prepared with: Workspace, agent and workflow key."""
    metadata = session.metadata_ if isinstance(session.metadata_, dict) else {}
    return {
        "project_id": str(session.project_id or ""),
        "agent_id": str(metadata.get("agent_definition_id") or ""),
        "workflow_key": str(metadata.get("workflow_key") or ""),
        "user_id": str(session.user_id or ""),
    }


def _same(now: dict[str, Any], then: dict[str, Any]) -> bool:
    if now.get("digest") and then.get("digest"):
        return now["digest"] == then["digest"] and now.get("ref") == then.get("ref")
    return now.get("ref") == then.get("ref") and now.get("source") == then.get("source")


def compare_prompt_refs(
    setup_refs: dict[str, dict[str, Any]],
    turn_refs: dict[str, dict[str, Any]],
    *,
    catalog_refs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Per key: the turn's ref next to the ref a turn renders now (``catalog_refs`` covers loop keys)."""
    current = {**(catalog_refs or {}), **setup_refs}
    keys: list[dict[str, Any]] = []
    for key in sorted(set(setup_refs) | set(turn_refs)):
        now, then = current.get(key), turn_refs.get(key)
        if then:
            state = "same" if now is not None and _same(now, then) else "changed"
        else:
            state = "setup_only"
        keys.append({"key": key, "turn": (then or {}).get("ref"), "turn_source": (then or {}).get("source"),
                     "now": (now or {}).get("ref"), "now_source": (now or {}).get("source"), "state": state})
    changed = [item for item in keys if item["state"] == "changed"]
    return {
        "matches": not changed,
        "changed": len(changed),
        "same": sum(1 for item in keys if item["state"] == "same"),
        "setup_only": sum(1 for item in keys if item["state"] == "setup_only"),
        "keys": keys,
    }


__all__ = ["compare_prompt_refs", "latest_turn_record", "session_setup_inputs"]
