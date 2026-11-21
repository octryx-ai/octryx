"""Failure policy of connectors and task runs: the constants, the decisions and how they are described."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ...models import FailedTaskRun
from ...time_utils import ensure_utc

CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
CIRCUIT_BREAKER_RETRY_DELAYS_SECONDS = [2, 8, 30]
FAILED_TASK_RETRY_DELAYS_SECONDS = [0, 1, 4, 16]
FAILED_TASK_RETRY_POLICY_NAME = "failed_task_run_backoff"
FAILED_TASK_RETRYABLE_STATUS = "pending_retry"
FAILED_TASK_TERMINAL_STATUS = "dead_letter"
FAILED_TASK_RESOLVED_STATUS = "resolved"
FAILED_TASK_QUEUE_RETRY_STATUS = "retry_pending"
FAILED_TASK_QUEUE_TERMINAL_STATUS = "dead_letter"
FAILED_TASK_QUEUE_FAILED_STATUS = "failed"
FAILED_TASK_RUN_FAILURE_STATUS = "error"
FAILED_TASK_RETRY_MAX_ATTEMPTS = len(FAILED_TASK_RETRY_DELAYS_SECONDS)
# A run refused by execution admission (typed ActionAdmissionError / AgentDefinitionExecutionError)
# needs a configuration change, not time: terminal at once, never scheduled for retry. The status column is
# an unconstrained String(32) (no CHECK in the model or any revision), so this closed value needs no migration.
FAILED_TASK_ADMISSION_REFUSED_STATUS = "admission_refused"
FAILED_TASK_ADMISSION_REFUSED_REASON = "execution_admission_refused"
FAILED_TASK_ADMISSION_REFUSAL_POLICY_NAME = "execution_admission_refusal"
# An Action of a checked-reply agent whose turn ended without a satisfied final reply (the
# reply broke the contract, or no checked final exists). Rerunning the same turn cannot repair a
# reply or a contract, so it is terminal exactly like an admission refusal.
FAILED_TASK_REPLY_CONTRACT_VIOLATION_STATUS = "reply_contract_violation"
FAILED_TASK_REPLY_CONTRACT_VIOLATION_REASON = "agent_reply_contract_violation"
FAILED_TASK_REPLY_CONTRACT_POLICY_NAME = "reply_contract_violation"
# An Action turn the runtime explicitly recorded as ``stopped`` with a closed stop reason (for
# example an answer-evidence refusal). Rerunning the same turn cannot change the governed decision that
# stopped it, so it is terminal as well.
FAILED_TASK_RUNTIME_STOPPED_STATUS = "runtime_stopped"
FAILED_TASK_RUNTIME_STOPPED_REASON = "agent_turn_runtime_stopped"
FAILED_TASK_RUNTIME_STOPPED_POLICY_NAME = "runtime_stopped"
# A content policy refused the content the Action's turn would send (for example a
# hostile alert read through a tool). The same content matches again on every rerun: a permanent refusal, terminal at
# once. Set only from the turn's typed failure class (``content_security.refusal``), never from the error text.
FAILED_TASK_CONTENT_BLOCKED_STATUS = "content_blocked"
FAILED_TASK_CONTENT_BLOCKED_REASON = "agent_turn_content_blocked"
FAILED_TASK_CONTENT_BLOCKED_POLICY_NAME = "content_blocked"
# Terminal statuses that never had a retry schedule: status -> (decision reason, policy name).
_TERMINAL_POLICIES: dict[str, tuple[str, str]] = {
    FAILED_TASK_ADMISSION_REFUSED_STATUS: (
        FAILED_TASK_ADMISSION_REFUSED_REASON,
        FAILED_TASK_ADMISSION_REFUSAL_POLICY_NAME,
    ),
    FAILED_TASK_REPLY_CONTRACT_VIOLATION_STATUS: (
        FAILED_TASK_REPLY_CONTRACT_VIOLATION_REASON,
        FAILED_TASK_REPLY_CONTRACT_POLICY_NAME,
    ),
    FAILED_TASK_RUNTIME_STOPPED_STATUS: (
        FAILED_TASK_RUNTIME_STOPPED_REASON,
        FAILED_TASK_RUNTIME_STOPPED_POLICY_NAME,
    ),
    FAILED_TASK_CONTENT_BLOCKED_STATUS: (
        FAILED_TASK_CONTENT_BLOCKED_REASON,
        FAILED_TASK_CONTENT_BLOCKED_POLICY_NAME,
    ),
}

_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+|((?:ghp_|gho_|github_pat_|glpat-|sk-)[A-Za-z0-9._-]+)"
)

_KEYWORD_CONNECTOR_MAP = {
    "jira": "jira",
    "confluence": "confluence",
    "bitbucket": "bitbucket",
    "k8s": "kubernetes",
    "kubernetes": "kubernetes",
    "grafana": "grafana",
    "prometheus": "prometheus",
    "loki": "loki",
    "servicenow": "servicenow",
    "elasticsearch": "elasticsearch",
    "notion": "notion",
    "sharepoint": "sharepoint",
    "github": "github",
    "gitlab": "gitlab",
    "aws": "aws",
    "azure": "azure",
    "gcp": "gcp",
}


@dataclass
class CircuitBreakerDecision:
    allowed: bool
    connector_name: str
    state: str
    reason: str = ""
    next_retry_at: str | None = None


@dataclass(frozen=True)
class TaskFailureDecision:
    failed_task_run_id: str
    task_id: str
    task_run_id: str
    status: str
    reason: str
    retryable: bool
    terminal: bool
    retry_count: int
    retry_delay_seconds: int | None
    next_retry_at: str | None
    failure_message: str | None
    queue_status: str
    task_run_status: str
    retry_policy: str
    max_retry_attempts: int
    retry_delays_seconds: tuple[int, ...] = tuple(FAILED_TASK_RETRY_DELAYS_SECONDS)

    def as_dict(self) -> dict[str, Any]:
        return {
            "failed_task_run_id": self.failed_task_run_id,
            "task_id": self.task_id,
            "task_run_id": self.task_run_id,
            "status": self.status,
            "reason": self.reason,
            "retryable": self.retryable,
            "terminal": self.terminal,
            "retry_count": self.retry_count,
            "retry_delay_seconds": self.retry_delay_seconds,
            "next_retry_at": self.next_retry_at,
            "failure_message": self.failure_message,
            "queue_status": self.queue_status,
            "task_run_status": self.task_run_status,
            "retry_policy": {
                "name": self.retry_policy,
                "delays_seconds": list(self.retry_delays_seconds),
                "max_retry_attempts": self.max_retry_attempts,
            },
        }


def infer_connector_name(tool_name: str) -> str | None:
    normalized = str(tool_name or "").strip().lower()
    if normalized.startswith("mcp__"):
        return "mcp"
    for keyword, connector_name in _KEYWORD_CONNECTOR_MAP.items():
        if keyword in normalized:
            return connector_name
    return None


def describe_failed_task_run(
    row: FailedTaskRun,
    *,
    retry_delay_seconds: int | None = None,
) -> TaskFailureDecision:
    status = str(row.status or FAILED_TASK_RETRYABLE_STATUS)
    terminal_policy = _TERMINAL_POLICIES.get(status)
    refused = terminal_policy is not None
    retryable = status == FAILED_TASK_RETRYABLE_STATUS
    terminal = status == FAILED_TASK_TERMINAL_STATUS or refused
    queue_status = FAILED_TASK_QUEUE_FAILED_STATUS
    if retryable:
        queue_status = FAILED_TASK_QUEUE_RETRY_STATUS
    elif terminal and not refused:
        queue_status = FAILED_TASK_QUEUE_TERMINAL_STATUS
    next_retry_at = ensure_utc(row.next_retry_at).isoformat() if row.next_retry_at else None
    reason = _failed_task_reason(status=status, retryable=retryable, terminal=terminal)
    return TaskFailureDecision(
        failed_task_run_id=row.id,
        task_id=row.task_id,
        task_run_id=row.task_run_id,
        status=status,
        reason=reason,
        retryable=retryable,
        terminal=terminal,
        retry_count=int(row.retry_count or 0),
        retry_delay_seconds=retry_delay_seconds,
        next_retry_at=next_retry_at,
        failure_message=row.last_error,
        queue_status=queue_status,
        task_run_status=FAILED_TASK_RUN_FAILURE_STATUS if status != FAILED_TASK_RESOLVED_STATUS else "success",
        # A terminal policy never had a retry schedule: report no delays and no attempts instead of the backoff.
        retry_policy=terminal_policy[1] if terminal_policy else FAILED_TASK_RETRY_POLICY_NAME,
        max_retry_attempts=0 if refused else FAILED_TASK_RETRY_MAX_ATTEMPTS,
        retry_delays_seconds=() if refused else tuple(FAILED_TASK_RETRY_DELAYS_SECONDS),
    )


def sanitize_task_failure_message(error: str) -> str | None:
    normalized = " ".join(str(error or "").strip().split())
    if not normalized:
        return None

    def _replace_secret(match: re.Match[str]) -> str:
        bearer_prefix = match.group(1)
        if bearer_prefix:
            return f"{bearer_prefix}[redacted]"
        return "[redacted]"

    return _SECRET_VALUE_PATTERN.sub(_replace_secret, normalized)[:4000]


def _failed_task_reason(*, status: str, retryable: bool, terminal: bool) -> str:
    if status in _TERMINAL_POLICIES:
        return _TERMINAL_POLICIES[status][0]
    if retryable:
        return "retry_scheduled"
    if terminal:
        return "retry_policy_exhausted"
    if status == FAILED_TASK_RESOLVED_STATUS:
        return "retry_resolved"
    return "failure_recorded"
