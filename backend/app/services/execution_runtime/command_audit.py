"""One durable audit row per server-side command an agent or a run causes."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

RESOURCE_TYPE = "server_command"
ACTION_REFUSED = "server_command.refused"
ACTION_EXECUTED = "server_command.executed"
AUDIT_UNAVAILABLE = "server_command_audit_unavailable"
MAX_COMMAND = 2000
_TOKEN = re.compile(r"[A-Za-z0-9+/=_-]{24,}")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Z0-9_]*(SECRET|TOKEN|PASSWORD|PASSWD|PWD|API_?KEY|PRIVATE_?KEY|ACCESS_?KEY|CREDENTIAL|DATABASE_URL|"
    r"DSN|AUTH)[A-Z0-9_]*)(\s*[=:]\s*)(\S+)")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+\S+")


@dataclass(frozen=True, slots=True)
class CommandActor:
    db: Any
    user_id: str | None
    session_id: str | None = None
    tool_name: str = ""
    workflow_run_id: str | None = None
    # The Workspace the commands act in: the run's; a tool call's comes from its session.
    project_id: str | None = None


@dataclass(slots=True)
class AuditHandle:
    row: Any
    db: Any


class CommandAuditUnavailableError(RuntimeError):
    code = AUDIT_UNAVAILABLE


_ACTOR: ContextVar[CommandActor | None] = ContextVar("server_command_actor", default=None)


def current_actor() -> CommandActor | None:
    return _ACTOR.get()


@contextmanager
def command_actor(actor: CommandActor | None) -> Iterator[None]:
    token = _ACTOR.set(actor)
    try:
        yield
    finally:
        _ACTOR.reset(token)


@contextmanager
def run_actor(db: Any, run: Any, *, tool_name: str) -> Iterator[None]:
    if current_actor() is not None or run is None:
        yield
        return
    with command_actor(CommandActor(db=db, user_id=getattr(run, "requested_by", None), tool_name=tool_name,
                                    workflow_run_id=getattr(run, "id", None),
                                    project_id=getattr(run, "project_id", None))):
        yield


def masked_command(command: str | Sequence[str]) -> str:
    text = command if isinstance(command, str) else " ".join(str(word) for word in command)
    text = _BEARER.sub(lambda match: f"{match.group(1)} ***", text)
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(3)}***", text)
    text = _TOKEN.sub("***", text)
    return text[:MAX_COMMAND]


async def _session(db: Any, session_id: str | None) -> Any:
    if db is None or not session_id:
        return None
    try:
        from ...models import Session

        return await db.get(Session, session_id)
    except Exception:  # noqa: BLE001 - the session is context, never a reason to refuse
        return None


async def record(command: str | Sequence[str], *, verdict: str, where: str, reason: str | None = None,
                 actor: CommandActor | None = None) -> AuditHandle | None:
    actor = actor or current_actor()
    if actor is None:
        return None
    if actor.db is None or not actor.user_id:
        raise CommandAuditUnavailableError("no database session or user to audit the server command")
    from ...models import AuditLog

    session = None if actor.workflow_run_id and actor.project_id else await _session(actor.db, actor.session_id)
    metadata = dict(getattr(session, "metadata_", None) or {})
    run_id = actor.workflow_run_id or (str(metadata["workflow_run_id"]) if metadata.get("workflow_run_id") else None)
    workspace = actor.project_id or getattr(session, "project_id", None)
    details = {"tool": actor.tool_name, "where": where, "verdict": verdict, "command": masked_command(command),
               "session_id": actor.session_id, "workflow_run_id": run_id, "exit_code": None,
               **({"reason": reason} if reason else {})}
    row = AuditLog(user_id=actor.user_id, session_id=actor.session_id, project_id=workspace,
                   action=ACTION_REFUSED if verdict == "refused" else ACTION_EXECUTED,
                   resource_type=RESOURCE_TYPE, resource_id=run_id or actor.session_id, details=details)
    try:
        actor.db.add(row)
        await actor.db.flush()
    except Exception as error:  # noqa: BLE001 - any failure to write refuses the command
        logger.warning("server command audit could not be written: where=%s error=%s", where, type(error).__name__)
        raise CommandAuditUnavailableError("the server command audit row could not be written") from error
    return AuditHandle(row, actor.db)


async def record_exit(handle: AuditHandle | None, exit_code: int | None, *, timed_out: bool = False) -> None:
    if handle is None:
        return
    handle.row.details = {**dict(handle.row.details or {}), "exit_code": exit_code,
                          **({"timed_out": True} if timed_out else {})}
    try:
        await handle.db.flush()
    except Exception:  # noqa: BLE001 - the command already ran; its row exists
        logger.warning("server command exit code could not be added to its audit row")


def unavailable_payload(command: str | Sequence[str] = "") -> dict[str, Any]:
    shown = command if isinstance(command, str) else " ".join(str(word) for word in command)
    return {"error": "The command was not run: its audit record could not be written.",
            "error_code": AUDIT_UNAVAILABLE, "code": AUDIT_UNAVAILABLE, "command": masked_command(shown)}


__all__ = [
    "ACTION_EXECUTED", "ACTION_REFUSED", "AUDIT_UNAVAILABLE", "AuditHandle", "CommandActor",
    "CommandAuditUnavailableError", "command_actor", "current_actor", "masked_command", "record", "record_exit",
    "run_actor", "unavailable_payload",
]
