"""The "done means verified" gate for governed clients (``POST sessions/verification``).

Evaluated at Claude Code's ``Stop`` / ``SubagentStop`` from the ToolCall rows the
model gateway recorded on the shadow session (ordered by ``created_at``, then
``parameters.block_index``):

- no successful change-tool call (``verification.change_tools``) in the session:
  ``not_applicable``;
- after the last one, the last Bash call whose command has a segment matching a
  declared ``test_command_prefixes`` entry decides, using the tool result and the
  execution evidence of the launcher's PostToolUse/PostToolUseFailure hooks
  (``parameters.executed``, see ``tool_execution.py``):
  - evidence ``failed``: ``blocked / last_test_failed``;
  - green result (evidence ``succeeded`` or no evidence, which keeps clients
    without the hook working): ``passed``;
  - error result with evidence ``succeeded``: ``blocked / last_test_failed``;
  - error result without evidence: ``blocked / last_test_not_run`` (the call was
    refused before execution, e.g. at Claude Code's permission prompt);
  - no result yet: ``blocked / last_test_unconfirmed``;
- no such Bash call: ``blocked / no_test_after_last_change``;
- no verification configuration: ``needs_configuration``.

Not every change needs a test (a phone session that writes a ``test.txt`` must not be pushed to invent a pytest
run):

- **only code changes count:** a change to a document, text, picture or office file (:data:`NON_CODE_SUFFIXES`) needs
  no test; changes that are all such files are ``not_applicable / no_code_change``. A change without a known path
  counts as code;
- **the common test runners count** (:data:`COMMON_TEST_RUNNERS`, besides the Workspace's own prefixes): npm/pnpm/
  yarn test, vitest, jest, mvn, gradle, go test, cargo test, make test, tox, ``uv run pytest`` …;
- **no test setup, no test:** the client's Stop hook says whether the session's folder has a test setup at all
  (``test_setup``, ``clients/octryx-claude/octryx_claude/test_setup.py``). ``False`` makes an untested code change
  ``not_applicable / no_test_setup`` instead of a block; a test that ran still decides.

Token-prefix matching only; nothing guesses whether a command "looks like" a test.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ToolCall
from ..prompt_catalog import render_prompt
from .command_match import command_segments, segment_matches
from .contract import (
    EXECUTION_OUTCOME_FAILED,
    EXECUTION_OUTCOME_SUCCEEDED,
    STATE_NEEDS_CONFIGURATION,
    TOOL_CALL_EXECUTED_KEY,
    TOOL_CALL_SOURCE_GATEWAY,
    TOOL_CALL_STATUS_ERROR,
    TOOL_CALL_STATUS_SUCCESS,
)
from .policy import GatewayPolicy, VerificationConfig

STATE_PASSED = "passed"
STATE_BLOCKED = "blocked"
STATE_NOT_APPLICABLE = "not_applicable"

REASON_GREEN_TEST = "green_test_after_last_change"
REASON_NO_CHANGE = "no_change_in_session"
REASON_NO_TEST = "no_test_after_last_change"
REASON_TEST_FAILED = "last_test_failed"
REASON_TEST_UNCONFIRMED = "last_test_unconfirmed"
REASON_TEST_NOT_RUN = "last_test_not_run"
REASON_NOT_CONFIGURED = "verification_not_configured"
REASON_NO_CODE_CHANGE = "no_code_change"
REASON_NO_TEST_SETUP = "no_test_setup"

NON_CODE_SUFFIXES = (".txt", ".md", ".markdown", ".rst", ".adoc", ".org", ".csv", ".tsv", ".log", ".png", ".jpg",
                     ".jpeg", ".gif", ".webp", ".svg", ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls",
                     ".odt", ".ods", ".odp", ".drawio", ".excalidraw", ".mmd", ".puml")
COMMON_TEST_RUNNERS: tuple[tuple[str, ...], ...] = (
    ("pytest",), ("python", "-m", "pytest"), ("python3", "-m", "pytest"), ("uv", "run", "pytest"),
    ("poetry", "run", "pytest"), ("tox",), ("nox",), ("npm", "test"), ("npm", "run", "test"), ("pnpm", "test"),
    ("pnpm", "run", "test"), ("yarn", "test"), ("npx", "vitest"), ("npx", "jest"), ("vitest",), ("jest",),
    ("node", "--test"), ("mvn", "test"), ("mvn", "verify"), ("mvnw", "test"), ("mvnw", "verify"),
    ("gradle", "test"), ("gradlew", "test"), ("go", "test"), ("cargo", "test"), ("make", "test"),
    ("dotnet", "test"), ("bundle", "exec", "rspec"), ("rspec",),
)

BASH_TOOL = "Bash"
MAX_TOOL_CALLS = 5000
MAX_REPORTED_COMMAND_CHARS = 300

def _detail(reason: str) -> str:
    """The gate detail for ``reason`` (catalog key ``secure_work.gateway.gate.<reason>``)."""
    return render_prompt(f"secure_work.gateway.gate.{reason}")


@dataclass(frozen=True, slots=True)
class VerificationResult:
    state: str
    reason: str
    detail: str = ""
    last_change_tool: str | None = None
    last_test_command: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "reason": self.reason,
            "detail": self.detail,
            "last_change_tool": self.last_change_tool,
            "last_test_command": self.last_test_command,
        }


def _parameters(row: ToolCall) -> dict[str, Any]:
    return row.parameters if isinstance(row.parameters, dict) else {}


def _order_key(row: ToolCall) -> tuple[datetime, int]:
    block_index = _parameters(row).get("block_index")
    return (row.created_at or datetime.min, block_index if type(block_index) is int else 0)


def _is_gateway_row(row: ToolCall) -> bool:
    return _parameters(row).get("source") == TOOL_CALL_SOURCE_GATEWAY


def _is_green(row: ToolCall) -> bool:
    result = row.result if isinstance(row.result, dict) else None
    return row.status == TOOL_CALL_STATUS_SUCCESS and result is not None and result.get("is_error") is False


def _is_failed(row: ToolCall) -> bool:
    result = row.result if isinstance(row.result, dict) else {}
    return row.status == TOOL_CALL_STATUS_ERROR or result.get("is_error") is True


def _execution_outcome(row: ToolCall) -> str | None:
    executed = _parameters(row).get(TOOL_CALL_EXECUTED_KEY)
    outcome = executed.get("outcome") if isinstance(executed, dict) else None
    return outcome if outcome in (EXECUTION_OUTCOME_SUCCEEDED, EXECUTION_OUTCOME_FAILED) else None


def _test_reason(row: ToolCall) -> str:
    outcome = _execution_outcome(row)
    if outcome == EXECUTION_OUTCOME_FAILED:
        return REASON_TEST_FAILED
    if _is_green(row):
        return REASON_GREEN_TEST
    if _is_failed(row):
        return REASON_TEST_FAILED if outcome == EXECUTION_OUTCOME_SUCCEEDED else REASON_TEST_NOT_RUN
    return REASON_TEST_UNCONFIRMED


def _is_test(row: ToolCall, config: VerificationConfig) -> bool:
    if row.tool_name != BASH_TOOL:
        return False
    segments = command_segments(str(_parameters(row).get("command") or ""))
    prefixes = (*config.test_command_prefixes, *COMMON_TEST_RUNNERS)
    return bool(segments) and any(segment_matches(segment, prefix) for segment in segments for prefix in prefixes)


def _changed_path(row: ToolCall) -> str:
    tool_input = _parameters(row).get("input")
    if not isinstance(tool_input, dict):
        return ""
    return str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")


def _is_code_change(row: ToolCall, config: VerificationConfig) -> bool:
    if row.tool_name not in config.change_tools or not _is_green(row):
        return False
    path = _changed_path(row).lower()
    return not (path and path.endswith(NON_CODE_SUFFIXES))


def evaluate_verification(policy: GatewayPolicy | None, rows: Sequence[ToolCall], *,
                          test_setup: bool | None = None) -> VerificationResult:
    """The gate decision for these ToolCall rows (``test_setup``: the client's finding, ``None`` unknown). Pure."""

    config = policy.verification if policy is not None else None
    if config is None:
        return VerificationResult(STATE_NEEDS_CONFIGURATION, REASON_NOT_CONFIGURED, _detail(REASON_NOT_CONFIGURED))
    ordered = sorted((row for row in rows if _is_gateway_row(row)), key=_order_key)
    last_change = next(
        (index for index in range(len(ordered) - 1, -1, -1) if _is_code_change(ordered[index], config)),
        None,
    )
    if last_change is None:
        any_change = any(row.tool_name in config.change_tools and _is_green(row) for row in ordered)
        return VerificationResult(STATE_NOT_APPLICABLE, REASON_NO_CODE_CHANGE if any_change else REASON_NO_CHANGE)
    change_tool = ordered[last_change].tool_name
    tests = [row for row in ordered[last_change + 1 :] if _is_test(row, config)]
    if not tests:
        if test_setup is False:
            return VerificationResult(STATE_NOT_APPLICABLE, REASON_NO_TEST_SETUP, "", change_tool)
        return VerificationResult(STATE_BLOCKED, REASON_NO_TEST, _detail(REASON_NO_TEST), change_tool)
    last_test = tests[-1]
    command = str(_parameters(last_test).get("command") or "")[:MAX_REPORTED_COMMAND_CHARS]
    reason = _test_reason(last_test)
    if reason == REASON_GREEN_TEST:
        return VerificationResult(STATE_PASSED, REASON_GREEN_TEST, "", change_tool, command)
    return VerificationResult(STATE_BLOCKED, reason, _detail(reason), change_tool, command)


async def session_tool_calls(db: AsyncSession, session_id: str) -> list[ToolCall]:
    """The session's ToolCall rows (bounded; the newest ``MAX_TOOL_CALLS`` when larger)."""

    rows = (
        (
            await db.execute(
                select(ToolCall)
                .where(ToolCall.session_id == session_id)
                .order_by(ToolCall.created_at.desc())
                .limit(MAX_TOOL_CALLS)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


__all__ = [
    "REASON_GREEN_TEST",
    "COMMON_TEST_RUNNERS",
    "NON_CODE_SUFFIXES",
    "REASON_NO_CHANGE",
    "REASON_NO_CODE_CHANGE",
    "REASON_NO_TEST_SETUP",
    "REASON_NO_TEST",
    "REASON_NOT_CONFIGURED",
    "REASON_TEST_FAILED",
    "REASON_TEST_NOT_RUN",
    "REASON_TEST_UNCONFIRMED",
    "STATE_BLOCKED",
    "STATE_NOT_APPLICABLE",
    "STATE_PASSED",
    "VerificationResult",
    "evaluate_verification",
    "session_tool_calls",
]
