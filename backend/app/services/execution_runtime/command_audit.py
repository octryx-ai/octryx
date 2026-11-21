"""One durable audit row per server-side command an agent or a run causes.

Every command the server runs for an agent (``bash``, ``run_cli_command``, ``start_runtime_process``,
``run_validation_commands``, the code-quality runner, the declared test/lint commands, ``workspace.prepare``, and
whatever reaches ``execute_with_runtime`` from them) writes an ``audit_log`` row BEFORE it runs:
``action`` ``server_command.refused`` (with the reason code) or ``server_command.executed`` (the exit code is added
after the run), ``resource_type`` ``server_command``, ``details`` with the tool, the session, the workflow run, where
it was decided and the command — truncated to 2000 characters, token-like strings (24+ characters of
``[A-Za-z0-9+/=_-]``) and the values of secret-named variables masked. Command output is never stored.

Who caused the command is the ``CommandActor`` of the context (``command_actor``): the tool registry sets it for a
tool call, a run's platform step for its requester. Fail-closed: with an actor, a row that cannot be written means
the command does not run (``CommandAuditUnavailableError``); without a database session there is nothing durable to
write to, so that is a refusal too. A platform-internal command (its own git in a snapshot, no actor) writes no row.
"""

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
    """Who caused the server commands of this context (``db``: the session the rows are written with)."""

    db: Any
    user_id: str | None
    session_id: str | None = None
    tool_name: str = ""
    workflow_run_id: str | None = None


@dataclass(slots=True)
class AuditHandle:
    """A written row and the session it was written with (the exit code goes on it after the run)."""

    row: Any
    db: Any


class CommandAuditUnavailableError(RuntimeError):
    """The audit row could not be written: the command does not run (fail-closed)."""

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
    """A run's platform step (``workspace.prepare``, a lint gate) acts as the run's requester, unless a tool call of
    a person already set the actor."""
    if current_actor() is not None or run is None:
        yield
        return
    with command_actor(CommandActor(db=db, user_id=getattr(run, "requested_by", None), tool_name=tool_name,
                                    workflow_run_id=getattr(run, "id", None))):
        yield


def masked_command(command: str | Sequence[str]) -> str:
    """The command as stored: secret-named values, auth headers and token-like strings masked, 2000 characters."""
    text = command if isinstance(command, str) else " ".join(str(word) for word in command)
    text = _BEARER.sub(lambda match: f"{match.group(1)} ***", text)
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(3)}***", text)
    text = _TOKEN.sub("***", text)
    return text[:MAX_COMMAND]


async def _workflow_run_id(db: Any, session_id: str | None) -> str | None:
    if db is None or not session_id:
        return None
    try:
        from ...models import Session

        session = await db.get(Session, session_id)
    except Exception:  # noqa: BLE001 - the run id is context, never a reason to refuse
        return None
    value = dict(getattr(session, "metadata_", None) or {}).get("workflow_run_id") if session is not None else None
    return str(value) if value else None


async def record(command: str | Sequence[str], *, verdict: str, where: str, reason: str | None = None,
                 actor: CommandActor | None = None) -> AuditHandle | None:
    """Write the row for ``command`` before it runs (``verdict``: ``refused`` | ``executed``); ``None`` without an
    actor (a platform-internal command). Raises ``CommandAuditUnavailableError`` when the row cannot be written."""
    actor = actor or current_actor()
    if actor is None:
        return None
    if actor.db is None or not actor.user_id:
        raise CommandAuditUnavailableError("no database session or user to audit the server command")
    from ...models import AuditLog

    run_id = actor.workflow_run_id or await _workflow_run_id(actor.db, actor.session_id)
    details = {"tool": actor.tool_name, "where": where, "verdict": verdict, "command": masked_command(command),
               "session_id": actor.session_id, "workflow_run_id": run_id, "exit_code": None,
               **({"reason": reason} if reason else {})}
    row = AuditLog(user_id=actor.user_id, session_id=actor.session_id,
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
    """The exit code of an executed command on its row (never its output)."""
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
