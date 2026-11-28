"""A launcher's preparation report, as the gateway receives it (``POST sessions/workspace-preparation``)."""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session
from ..records import active_run_for_session, lock_run

logger = logging.getLogger(__name__)
# A slow report logs its steps: the API keeps no access log that tells which step took the time.
SLOW_REPORT_SECONDS = 5.0

REASON_NO_RUN = "workflow_run_not_bound"
MAX_ITEMS = 20
MAX_TEXT = 2000


def _text(value: Any, limit: int = MAX_TEXT) -> str:
    return str(value or "")[:limit]


def _clean(payload: dict[str, Any]) -> dict[str, Any]:
    branch = payload.get("branch") if isinstance(payload.get("branch"), dict) else {}
    environment = payload.get("environment") if isinstance(payload.get("environment"), dict) else {}
    return {
        "node_id": _text(payload.get("node_id"), 120) or None,
        "entry": payload.get("entry") if type(payload.get("entry")) is int else None,
        "root": _text(payload.get("root"), 1000), "runtime": _text(payload.get("runtime"), 20) or "launcher",
        "remote_url": _text(payload.get("remote_url"), 500) or None,
        "branch": {"state": _text(branch.get("state"), 20), "name": _text(branch.get("name"), 250),
                   "current": _text(branch.get("current"), 250), "head": _text(branch.get("head"), 64),
                   "detail": _text(branch.get("detail"), 500),
                   "dirty_files": [_text(item, 300) for item in list(branch.get("dirty_files") or [])[:MAX_ITEMS]]},
        "environment": {
            "state": _text(environment.get("state"), 20), "reason": _text(environment.get("reason")),
            "probes": [{"what": _text(item.get("what"), 200), "ok": item.get("ok") is True,
                        "detail": _text(item.get("detail"), 500)}
                       for item in list(environment.get("probes") or [])[:MAX_ITEMS] if isinstance(item, dict)],
            "setup": [{"command": _text(item.get("command"), 1000),
                       "exit_code": item.get("exit_code") if type(item.get("exit_code")) is int else None,
                       "output": _text(item.get("output")), "seconds": item.get("seconds")}
                      for item in list(environment.get("setup") or [])[:MAX_ITEMS] if isinstance(item, dict)],
            **_file_report(environment.get("environment_file")),
        },
        **_reset_report(payload.get("wip_reset")),
    }


def _reset_report(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    files = raw.get("files") if type(raw.get("files")) is int else None
    return {"wip_reset": {"state": _text(raw.get("state"), 20), "sha": _text(raw.get("sha"), 40), "files": files,
                          "backup": _text(raw.get("backup"), 300)}}


def _file_report(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    commands = raw.get("commands") if isinstance(raw.get("commands"), dict) else {}
    return {"environment_file": {
        "file": _text(raw.get("file"), 300), "state": _text(raw.get("state"), 40),
        "commands": {key: _text(commands.get(key), 1000) for key in ("test", "lint", "system_test")
                     if _text(commands.get(key), 1000)}}}


async def report_preparation(db: AsyncSession, *, session: Session, payload: dict[str, Any]) -> dict[str, Any] | None:
    from ..octryx.contract import run_contract, session_principal
    from ..teamwork.item_sessions import record_item_preparation
    from .preparation import record_report

    started = time.perf_counter()
    run = await active_run_for_session(db, session.id)
    if run is None:
        return None
    run = await lock_run(db, run)
    locked = time.perf_counter()
    report = _clean(payload)
    # A teamwork item's worktree reports for itself, never as the run's (main folder's) preparation.
    state = await record_item_preparation(db, run, session, report) or await record_report(
        db, run, report, session_id=session.id)
    recorded = time.perf_counter()
    contract = await run_contract(db, run, principal=await session_principal(db, session), session=session)
    done = time.perf_counter()
    if done - started >= SLOW_REPORT_SECONDS:
        logger.warning("workspace_preparation_report slow run=%s node=%s total=%.1fs lock_wait=%.1fs record=%.1fs "
                       "contract=%.1fs", run.id, run.current_node_id, done - started, locked - started,
                       recorded - locked, done - recorded)
    paused = contract.get("paused") or {}
    return {"state": state, "reason": paused.get("reason") if state != "ready" else None,
            "detail": paused.get("detail") if state != "ready" else None, "workflow_run": contract}


__all__ = ["REASON_NO_RUN", "report_preparation"]
