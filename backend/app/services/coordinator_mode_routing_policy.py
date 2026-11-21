from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

CoordinatorExecutionMode = Literal[
    "sub_agent_group",
    "worker_delegation",
    "deterministic_workflow",
    "manual_review",
]


@dataclass(frozen=True)
class CoordinatorRoutingSignals:
    """Explicit routing inputs for coordinator-mode selection.

    The turn's request routing builds these signals and evaluates them without side
    effects.
    """

    deterministic_workflow_id: str | None = None
    target_worker_id: str | None = None
    required_worker_domain: str | None = None
    requested_action: str | None = None
    requires_worker_assignment: bool = False
    requires_parallel_children: bool = False
    expected_child_count: int = 0
    requires_parent_resume: bool = False


@dataclass(frozen=True)
class CoordinatorRoutingDecision:
    mode: CoordinatorExecutionMode
    rationale: str
    conflicts: tuple[str, ...] = field(default_factory=tuple)

    @property
    def requires_manual_review(self) -> bool:
        return self.mode == "manual_review"


def _mixed_signal_decision(
    *, has_workflow_signal: bool, has_worker_signal: bool, has_sub_agent_group_signal: bool
) -> CoordinatorRoutingDecision:
    conflicts: list[str] = []
    if has_workflow_signal:
        conflicts.append("deterministic workflow matched")
    if has_worker_signal:
        conflicts.append("worker assignment matched")
    if has_sub_agent_group_signal:
        conflicts.append("sub-agent fan-out matched")
    return CoordinatorRoutingDecision(
        mode="manual_review",
        rationale=(
            "Routing signals span multiple coordinator modes; keep the decision explicit "
            "instead of silently overriding deterministic workflow, worker delegation, "
            "or sub-agent orchestration boundaries."
        ),
        conflicts=tuple(conflicts),
    )


def _sub_agent_group_decision(signals: CoordinatorRoutingSignals, child_count: int) -> CoordinatorRoutingDecision:
    if child_count <= 1 and not signals.requires_parallel_children and signals.requires_parent_resume:
        rationale = (
            "Use sub_agent_group because the parent session must suspend and resume around "
            "a child-run lifecycle, even without wide fan-out."
        )
    else:
        rationale = (
            "Use sub_agent_group when the coordinator must launch or track multiple child "
            "runs under one parent session and resume after they finish or time out."
        )
    return CoordinatorRoutingDecision(mode="sub_agent_group", rationale=rationale)


def _worker_delegation_decision(
    *, worker_target_id: str, worker_domain: str, requested_action: str
) -> CoordinatorRoutingDecision:
    parts: list[str] = ["Use worker_delegation when work must be assigned to an existing worker"]
    if worker_target_id:
        parts.append("with an explicit target worker")
    elif worker_domain:
        parts.append(f"for the '{worker_domain}' worker domain")
    elif requested_action:
        parts.append(f"for the '{requested_action}' action capability")
    return CoordinatorRoutingDecision(mode="worker_delegation", rationale=" ".join(parts) + ".")


def decide_coordinator_mode(signals: CoordinatorRoutingSignals) -> CoordinatorRoutingDecision:
    """Route coordinator work to the bounded execution mode that owns it.

    Policy intent:
    - `deterministic_workflow` owns repeatable, contract-driven task workflows.
    - `worker_delegation` owns assignment to an existing worker identity/domain.
    - `sub_agent_group` owns parent/child orchestration across multiple child runs.
    - mixed signals stay explicit and return `manual_review` instead of hiding policy
      inside orchestration entrypoints.
    """

    workflow_id = str(signals.deterministic_workflow_id or "").strip()
    worker_target_id = str(signals.target_worker_id or "").strip()
    worker_domain = str(signals.required_worker_domain or "").strip()
    requested_action = str(signals.requested_action or "").strip()

    has_workflow_signal = bool(workflow_id)
    has_worker_signal = bool(
        signals.requires_worker_assignment or worker_target_id or worker_domain or requested_action
    )
    child_count = max(int(signals.expected_child_count or 0), 0)
    has_sub_agent_group_signal = bool(
        signals.requires_parallel_children or signals.requires_parent_resume or child_count > 1
    )

    active_modes = sum((has_workflow_signal, has_worker_signal, has_sub_agent_group_signal))
    if active_modes > 1:
        return _mixed_signal_decision(
            has_workflow_signal=has_workflow_signal,
            has_worker_signal=has_worker_signal,
            has_sub_agent_group_signal=has_sub_agent_group_signal,
        )

    if has_sub_agent_group_signal:
        return _sub_agent_group_decision(signals, child_count)

    if has_worker_signal:
        return _worker_delegation_decision(
            worker_target_id=worker_target_id, worker_domain=worker_domain, requested_action=requested_action
        )

    if has_workflow_signal:
        return CoordinatorRoutingDecision(
            mode="deterministic_workflow",
            rationale=(
                "Use deterministic_workflow when a known workflow contract already prescribes "
                f"the task path, such as workflow '{workflow_id}'."
            ),
        )

    return CoordinatorRoutingDecision(
        mode="manual_review",
        rationale=(
            "No bounded coordinator mode matched. Keep the request on the direct loop or make "
            "the orchestration intent explicit before routing it through coordinator policy."
        ),
    )


__all__ = [
    "CoordinatorExecutionMode",
    "CoordinatorRoutingDecision",
    "CoordinatorRoutingSignals",
    "decide_coordinator_mode",
]
