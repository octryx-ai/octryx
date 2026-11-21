"""Whether an alert starts the webhook's Action, and why not.

Decided in this order, every outcome recorded on the event (never dropped silently):

1. **Needs setup**: the webhook has no Action, or the Action is paused, belongs to another
   Workspace, does not run an agent turn, declares no workflow (``capability_class``) or has no
   instruction. Nothing guesses a workflow: the alert waits with the reason.
1b. **Target**: an Action that opts in (``workflow_run.alert_target == "required"``) starts only
   for an alert that maps to exactly one of the Workspace's alert targets (``targets``); unmapped, ambiguous
   or an invalid target list is "needs setup" with the reason. Without the opt-in nothing is mapped and the
   alert is decided.
2. **Filter**: ``critical_warning`` (default) starts firing alerts of severity critical or warning
   (an alert without a severity counts as warning); ``all_firing`` starts every firing alert; ``all``
   starts resolved ones too. Otherwise ``skipped_resolved`` / ``skipped_filtered``.
3. **Repeat grouping**: for Alertmanager and Grafana (occurrence sources) the dedup of ``occurrence``:
   the same occurrence or a recurrence while the run is open → ``grouped`` with that run; a new occurrence
   shortly after it ended reopens (``started``). Other sources, and alerts without occurrences: the same
   fingerprint started a run within ``group_window_minutes`` → ``grouped`` with that run.
4. **Limit**: ``rate_limit_per_hour`` (1–1000, never unlimited) runs already started in the last hour →
   ``skipped_rate_limit``.

Test alerts are filtered like real ones but never grouped or limited.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.integration.webhook import Webhook, WebhookEvent
from ...scheduler.execution.action_admission import AGENT_TURN_TASK_TYPES
from ...time_utils import utc_now
from .normalize import NormalizedAlert
from .occurrence import KIND_NEW, DedupDecision, dedup_key, find_dedup, occurrences_of, service_of
from .targets import REASON_AMBIGUOUS, REASON_INVALID, REASON_UNMAPPED, AlertTarget, map_alert_target

OUTCOME_STARTED = "started"
OUTCOME_GROUPED = "grouped"
OUTCOME_SKIPPED_RESOLVED = "skipped_resolved"
OUTCOME_SKIPPED_FILTERED = "skipped_filtered"
OUTCOME_SKIPPED_RATE_LIMIT = "skipped_rate_limit"
OUTCOME_NEEDS_SETUP = "needs_setup"
OUTCOME_COMPLETED = "completed"
OUTCOME_FAILED = "failed"

ALERT_FILTERS = ("critical_warning", "all_firing", "all")
DEFAULT_RATE_LIMIT_PER_HOUR = 20

SETUP_NO_ACTION = "no_action"
SETUP_ACTION_PAUSED = "action_paused"
SETUP_ACTION_OTHER_WORKSPACE = "action_other_workspace"
SETUP_ACTION_NOT_AGENT_TURN = "action_not_agent_turn"
SETUP_ACTION_NO_WORKFLOW = "action_no_workflow"
SETUP_ACTION_NO_INSTRUCTION = "action_no_instruction"
SETUP_ALERT_TARGET_UNMAPPED = REASON_UNMAPPED
SETUP_ALERT_TARGET_AMBIGUOUS = REASON_AMBIGUOUS
SETUP_ALERT_TARGETS_INVALID = REASON_INVALID
TARGET_REQUIRED = "required"

SETUP_MESSAGES = {
    SETUP_NO_ACTION: "Choose the action this webhook starts.",
    SETUP_ACTION_PAUSED: "The action is paused.",
    SETUP_ACTION_OTHER_WORKSPACE: "The action belongs to a different Workspace.",
    SETUP_ACTION_NOT_AGENT_TURN: "The action does not run an agent.",
    SETUP_ACTION_NO_WORKFLOW: "The action has no workflow.",
    SETUP_ACTION_NO_INSTRUCTION: "The action has no instructions.",
    SETUP_ALERT_TARGET_UNMAPPED: "No alert target of the Workspace matches this alert's labels.",
    SETUP_ALERT_TARGET_AMBIGUOUS: "More than one alert target of the Workspace matches this alert.",
    SETUP_ALERT_TARGETS_INVALID: "The Workspace's alert targets are invalid; fix them in the Workspace settings.",
}


@dataclass(frozen=True)
class AlertDecision:
    outcome: str
    reason: str = ""
    grouped_with_run_id: str | None = None
    target: AlertTarget | None = None
    dedup: DedupDecision | None = None

    @property
    def starts(self) -> bool:
        return self.outcome == OUTCOME_STARTED


def action_setup_gap(webhook: Webhook, task: Any | None) -> str | None:
    """Why the webhook cannot start its Action, or ``None`` when it can."""
    if task is None:
        return SETUP_NO_ACTION
    if str(task.project_id or "") != str(webhook.project_id or ""):
        return SETUP_ACTION_OTHER_WORKSPACE
    if not task.is_active:
        return SETUP_ACTION_PAUSED
    if task.task_type not in AGENT_TURN_TASK_TYPES:
        return SETUP_ACTION_NOT_AGENT_TURN
    config = task.config if isinstance(task.config, dict) else {}
    if not str(config.get("capability_class") or "").strip():
        return SETUP_ACTION_NO_WORKFLOW
    if not str(config.get("prompt") or "").strip() and not str(config.get("agent_definition_id") or "").strip():
        return SETUP_ACTION_NO_INSTRUCTION
    return None


def target_required(task: Any | None) -> bool:
    """The Action opts in to mapped targets: ``config.workflow_run.alert_target == "required"``."""
    config = task.config if task is not None and isinstance(task.config, dict) else {}
    run = config.get("workflow_run") if isinstance(config.get("workflow_run"), dict) else {}
    return run.get("alert_target") == TARGET_REQUIRED


def passes_filter(alert_filter: str, alert: NormalizedAlert) -> str | None:
    """``None`` when the alert passes, else the skip outcome."""
    mode = alert_filter if alert_filter in ALERT_FILTERS else "critical_warning"
    if alert.status == "resolved" and mode != "all":
        return OUTCOME_SKIPPED_RESOLVED
    if mode == "critical_warning" and alert.severity == "info":
        return OUTCOME_SKIPPED_FILTERED
    return None


async def _previous_in_window(
    db: AsyncSession, webhook: Webhook, alert: NormalizedAlert, *, now: datetime
) -> WebhookEvent | None:
    """The last started event of the same fingerprint inside the webhook's group window, if it has one."""
    window = int(webhook.group_window_minutes or 0)
    if window <= 0:
        return None
    return (
        await db.execute(
            select(WebhookEvent)
            .where(
                WebhookEvent.webhook_id == webhook.id,
                WebhookEvent.fingerprint == alert.fingerprint,
                WebhookEvent.outcome.in_((OUTCOME_STARTED, OUTCOME_COMPLETED, OUTCOME_FAILED)),
                WebhookEvent.is_test.is_(False),
                WebhookEvent.received_at >= now - timedelta(minutes=window),
            )
            .order_by(WebhookEvent.received_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _rate_limited(db: AsyncSession, webhook: Webhook, *, now: datetime) -> bool:
    # There is no "unlimited": a missing or non-positive limit is the safe default.
    limit = int(webhook.rate_limit_per_hour or 0)
    if limit <= 0:
        limit = DEFAULT_RATE_LIMIT_PER_HOUR
    if limit > 0:
        started = (
            await db.execute(
                select(func.count())
                .select_from(WebhookEvent)
                .where(
                    WebhookEvent.webhook_id == webhook.id,
                    WebhookEvent.outcome.in_((OUTCOME_STARTED, OUTCOME_COMPLETED, OUTCOME_FAILED)),
                    WebhookEvent.is_test.is_(False),
                    WebhookEvent.received_at >= now - timedelta(hours=1),
                )
            )
        ).scalar_one()
        if int(started) >= limit:
            return True
    return False


async def decide(
    db: AsyncSession, webhook: Webhook, task: Any | None, alert: NormalizedAlert, *, is_test: bool = False,
    targets: list[AlertTarget] | None = None, target_required: bool = False, target_errors: Sequence[str] = (),
) -> AlertDecision:
    gap = action_setup_gap(webhook, task)
    if gap:
        return AlertDecision(OUTCOME_NEEDS_SETUP, gap)
    target: AlertTarget | None = None
    if target_required and target_errors:
        return AlertDecision(OUTCOME_NEEDS_SETUP, SETUP_ALERT_TARGETS_INVALID)
    if targets is not None or target_required:
        match = map_alert_target(list(targets or []) if not target_errors else [], alert)
        if match.target is None and target_required:
            return AlertDecision(OUTCOME_NEEDS_SETUP, match.reason or SETUP_ALERT_TARGET_UNMAPPED)
        target = match.target
    skipped = passes_filter(webhook.alert_filter or "critical_warning", alert)
    if skipped:
        return AlertDecision(skipped, target=target)
    fresh = DedupDecision(KIND_NEW, dedup_key(service_of(alert, target), alert.fingerprint), occurrences_of(alert))
    if is_test:
        return AlertDecision(OUTCOME_STARTED, target=target, dedup=fresh)
    now = utc_now()
    dedup = fresh
    if fresh.occurrences:
        dedup = await find_dedup(db, webhook, alert, target, now=now)
        if dedup.groups:
            return AlertDecision(OUTCOME_GROUPED, grouped_with_run_id=dedup.linked_task_run_id, target=target,
                                 dedup=dedup)
    else:
        previous = await _previous_in_window(db, webhook, alert, now=now)
        if previous is not None:
            return AlertDecision(OUTCOME_GROUPED, grouped_with_run_id=previous.task_run_id, target=target)
    if await _rate_limited(db, webhook, now=now):
        return AlertDecision(OUTCOME_SKIPPED_RATE_LIMIT, target=target, dedup=dedup)
    return AlertDecision(OUTCOME_STARTED, target=target, dedup=dedup)


__all__ = [
    "ALERT_FILTERS",
    "OUTCOME_COMPLETED",
    "OUTCOME_FAILED",
    "OUTCOME_GROUPED",
    "OUTCOME_NEEDS_SETUP",
    "OUTCOME_SKIPPED_FILTERED",
    "OUTCOME_SKIPPED_RATE_LIMIT",
    "OUTCOME_SKIPPED_RESOLVED",
    "OUTCOME_STARTED",
    "SETUP_ALERT_TARGETS_INVALID",
    "SETUP_ALERT_TARGET_AMBIGUOUS",
    "SETUP_ALERT_TARGET_UNMAPPED",
    "SETUP_MESSAGES",
    "TARGET_REQUIRED",
    "AlertDecision",
    "action_setup_gap",
    "decide",
    "passes_filter",
    "target_required",
]
