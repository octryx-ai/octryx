"""Worker selection and routing logic for task queue dispatch."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.worker_pool.helpers import _should_pause_low_priority, explicit_required_domain, infer_required_domain
from app.services.worker_pool.state import (
    _refresh_rate_limit_usage,
    get_or_create_worker_rate_limit,
)

from ...models import AgentWorker, Task, TaskQueueEntry, TaskRoutingRule, WorkerDomainExpertise

# The explicit routing conditions a rule can declare; nothing is inferred from task text.
ROUTING_CONDITION_TYPES = ("domain_match", "priority_level", "always", "worker_expertise")


@dataclass(frozen=True, slots=True)
class WorkerDispatchDecision:
    status: str
    reason: str
    worker_id: str | None
    required_domain: str
    matched_rule_id: str | None = None
    policy: str = "worker_dispatch_policy_v1"

    @property
    def selected(self) -> bool:
        return self.status == "selected" and self.worker_id is not None

    def as_dict(self) -> dict[str, object]:
        return {
            "policy": self.policy,
            "status": self.status,
            "reason": self.reason,
            "worker_id": self.worker_id,
            "required_domain": self.required_domain,
            "matched_rule_id": self.matched_rule_id,
        }


async def _match_routing_rule(
    db: AsyncSession,
    *,
    task: Task,
    queue_entry: TaskQueueEntry,
    rule: TaskRoutingRule,
    workers: list[AgentWorker],
    domain_scores: dict[str, WorkerDomainExpertise],
) -> AgentWorker | None:
    config = dict(rule.condition_config or {})
    target = dict(rule.target_config or {})
    current_domain = infer_required_domain(task, queue_entry)

    matches = False
    if rule.condition_type == "domain_match":
        matches = current_domain == str(config.get("domain") or "").strip().lower()
    elif rule.condition_type == "priority_level":
        matches = int(queue_entry.priority or 5) >= int(config.get("min_priority") or 1)
    elif rule.condition_type == "always":
        matches = True
    elif rule.condition_type == "worker_expertise":
        matches = current_domain == str(config.get("domain") or current_domain).strip().lower()
    if not matches:
        return None

    if rule.target_type == "specific_worker":
        worker_id = str(target.get("worker_id") or "").strip()
        return next((worker for worker in workers if worker.id == worker_id), None)

    if rule.target_type == "domain_expert":
        domain = str(target.get("domain") or current_domain).strip().lower()
        ranked = sorted(
            workers,
            key=lambda item: (
                float(
                    domain_scores.get(f"{item.id}:{domain}").success_rate
                    if domain_scores.get(f"{item.id}:{domain}")
                    else 0
                ),
                int(
                    domain_scores.get(f"{item.id}:{domain}").tasks_completed
                    if domain_scores.get(f"{item.id}:{domain}")
                    else 0
                ),
                int(item.runtime_state.available_slots if item.runtime_state else 0),
            ),
            reverse=True,
        )
        return ranked[0] if ranked else None

    return None


async def _eligible_workers(db: AsyncSession, project_id: str) -> list[AgentWorker]:
    workers = (
        (
            await db.execute(
                select(AgentWorker)
                .options(selectinload(AgentWorker.runtime_state), selectinload(AgentWorker.onboarding))
                .where(AgentWorker.project_id == project_id, AgentWorker.is_active.is_(True))
            )
        )
        .scalars()
        .all()
    )
    return [
        worker
        for worker in workers
        if worker.runtime_state
        and worker.onboarding
        and worker.onboarding.onboarding_status == "ready"
        and int(worker.runtime_state.available_slots or 0) > 0
    ]


async def select_dispatch_worker(
    db: AsyncSession,
    *,
    task: Task,
    queue_entry: TaskQueueEntry,
) -> tuple[AgentWorker | None, str | None]:
    worker, decision = await select_dispatch_worker_with_decision(db, task=task, queue_entry=queue_entry)
    return worker, None if decision.selected else decision.reason


async def select_dispatch_worker_with_decision(
    db: AsyncSession,
    *,
    task: Task,
    queue_entry: TaskQueueEntry,
) -> tuple[AgentWorker | None, WorkerDispatchDecision]:
    required_domain = infer_required_domain(task, queue_entry)
    workers = await _eligible_workers(db, task.project_id)
    if not workers:
        return None, _decision("skipped", "no_available_workers", required_domain=required_domain)

    if queue_entry.required_worker_id:
        worker = next((item for item in workers if item.id == queue_entry.required_worker_id), None)
        if worker:
            return worker, _decision(
                "selected",
                "required_worker",
                worker_id=worker.id,
                required_domain=required_domain,
            )
        return None, _decision("skipped", "required_worker_unavailable", required_domain=required_domain)

    rate_limit = await get_or_create_worker_rate_limit(db, task.project_id)
    await _refresh_rate_limit_usage(db, rate_limit)
    if _should_pause_low_priority(rate_limit, int(queue_entry.priority or 5)):
        return None, _decision("skipped", "paused_due_to_rate_limit", required_domain=required_domain)

    expertise_rows = (
        (
            await db.execute(
                select(WorkerDomainExpertise).where(
                    WorkerDomainExpertise.worker_id.in_([worker.id for worker in workers])
                )
            )
        )
        .scalars()
        .all()
    )
    expertise_lookup = {f"{row.worker_id}:{row.domain}": row for row in expertise_rows}

    routing_rules = (
        (
            await db.execute(
                select(TaskRoutingRule)
                .where(TaskRoutingRule.project_id == task.project_id, TaskRoutingRule.is_active == 1)
                .order_by(TaskRoutingRule.priority.asc(), TaskRoutingRule.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    for rule in routing_rules:
        matched = await _match_routing_rule(
            db,
            task=task,
            queue_entry=queue_entry,
            rule=rule,
            workers=workers,
            domain_scores=expertise_lookup,
        )
        if matched is not None:
            return matched, _decision(
                "selected",
                "routing_rule_match",
                worker_id=matched.id,
                required_domain=required_domain,
                matched_rule_id=rule.id,
            )

    if explicit_required_domain(task, queue_entry) is None:
        reason = "routing_policy_missing" if not routing_rules else "no_configured_route"
        return None, _decision("skipped", reason, required_domain=required_domain)

    ranked = sorted(
        workers,
        key=lambda worker: (
            float(
                expertise_lookup.get(f"{worker.id}:{required_domain}").success_rate
                if expertise_lookup.get(f"{worker.id}:{required_domain}")
                else 0
            ),
            int(
                expertise_lookup.get(f"{worker.id}:{required_domain}").tasks_completed
                if expertise_lookup.get(f"{worker.id}:{required_domain}")
                else 0
            ),
            int(worker.runtime_state.available_slots if worker.runtime_state else 0),
            -int(worker.runtime_state.active_tasks_count if worker.runtime_state else 0),
        ),
        reverse=True,
    )
    if not ranked:
        return None, _decision("skipped", "no_configured_route", required_domain=required_domain)
    worker = ranked[0]
    return worker, _decision(
        "selected",
        "domain_expertise_fallback",
        worker_id=worker.id,
        required_domain=required_domain,
    )


def _decision(
    status: str,
    reason: str,
    *,
    required_domain: str,
    worker_id: str | None = None,
    matched_rule_id: str | None = None,
) -> WorkerDispatchDecision:
    return WorkerDispatchDecision(
        status=status,
        reason=reason,
        worker_id=worker_id,
        required_domain=required_domain,
        matched_rule_id=matched_rule_id,
    )


__all__ = [
    "WorkerDispatchDecision",
    "select_dispatch_worker",
    "select_dispatch_worker_with_decision",
]
