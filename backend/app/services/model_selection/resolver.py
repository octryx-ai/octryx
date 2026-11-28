"""The one model resolver: which model answers, and what the fallback chain is."""

from __future__ import annotations

from dataclasses import dataclass, field

from .gates import CatalogModel, WorkspaceScope, gate, reason_text
from .snapshot import SelectionSnapshot

SOURCE_PERSON = "person"
SOURCE_AGENT = "agent"
SOURCE_STEP = "workflow_step"
SOURCE_TASK = "task_model"
SOURCE_WORKSPACE = "workspace_default"
SOURCE_PLATFORM = "platform_order"
SOURCE_LABELS = {
    SOURCE_PERSON: "Person chose",
    SOURCE_AGENT: "Agent pins",
    SOURCE_STEP: "Workflow step pins",
    SOURCE_TASK: "Task model",
    SOURCE_WORKSPACE: "Workspace default",
    SOURCE_PLATFORM: "Platform order",
}

REFUSAL_CHOICE_NOT_ALLOWED = "chosen_model_not_allowed"
REFUSAL_NO_CANDIDATE = "needs_configuration"


@dataclass(frozen=True, slots=True)
class ModelRequest:
    person_choice: str = ""  # catalog key the person picked; only an explicit pick counts
    agent_pin: str = ""
    step_pin: str = ""
    task: str = ""
    capability: str = ""


@dataclass(frozen=True, slots=True)
class TraceStep:
    label: str
    outcome: str  # "chosen" | "skipped" | "refused" | "none" | "info"
    detail: str


@dataclass(slots=True)
class Resolution:
    start: str = ""
    source: str = ""
    chain: list[str] = field(default_factory=list)
    refusal: str = ""
    refusal_detail: str = ""
    trace: list[TraceStep] = field(default_factory=list)

    @property
    def refused(self) -> bool:
        return bool(self.refusal)


def _name(snapshot: SelectionSnapshot, key: str) -> str:
    model = snapshot.model(key)
    return model.display_name if model else key


def candidates(snapshot: SelectionSnapshot, scope: WorkspaceScope, *, capability: str = "") -> list[CatalogModel]:
    return [model for model in snapshot.models.values() if not gate(model, scope, capability=capability)]


def _pins(snapshot: SelectionSnapshot, scope: WorkspaceScope, request: ModelRequest) -> list[tuple[str, str]]:
    task_key = (
        (dict(scope.task_overrides).get(request.task) or snapshot.task_models.get(request.task, ""))
        if request.task
        else ""
    )
    workspace_default = snapshot.by_target.get(scope.default_target_id, "") if scope.default_target_id else ""
    return [
        (SOURCE_AGENT, request.agent_pin),
        (SOURCE_STEP, request.step_pin),
        (SOURCE_TASK, task_key),
        (SOURCE_WORKSPACE, workspace_default),
    ]


def resolve_model(snapshot: SelectionSnapshot, scope: WorkspaceScope, request: ModelRequest) -> Resolution:
    result = Resolution()
    capability = request.capability

    if request.person_choice:
        reason = gate(snapshot.model(request.person_choice), scope, capability=capability)
        if reason:
            result.refusal, result.refusal_detail = REFUSAL_CHOICE_NOT_ALLOWED, reason_text(reason)
            result.trace.append(TraceStep(SOURCE_LABELS[SOURCE_PERSON], "refused",
                                          f"{_name(snapshot, request.person_choice)}: {reason_text(reason)}"))
            return result
        result.start, result.source = request.person_choice, SOURCE_PERSON
        result.trace.append(TraceStep(SOURCE_LABELS[SOURCE_PERSON], "chosen", _name(snapshot, request.person_choice)))
    else:
        result.trace.append(TraceStep(SOURCE_LABELS[SOURCE_PERSON], "none", "Automatic"))
        for source, key in _pins(snapshot, scope, request):
            if not key:
                continue
            reason = gate(snapshot.model(key), scope, capability=capability)
            if reason:
                result.trace.append(TraceStep(SOURCE_LABELS[source], "skipped",
                                              f"{_name(snapshot, key)}: {reason_text(reason)}"))
                continue
            result.start, result.source = key, source
            result.trace.append(TraceStep(SOURCE_LABELS[source], "chosen", _name(snapshot, key)))
            break
        if not result.start:
            for key in snapshot.order:
                reason = gate(snapshot.model(key), scope, capability=capability)
                if reason:
                    result.trace.append(TraceStep(SOURCE_LABELS[SOURCE_PLATFORM], "skipped",
                                                  f"{_name(snapshot, key)}: {reason_text(reason)}"))
                    continue
                result.start, result.source = key, SOURCE_PLATFORM
                result.trace.append(TraceStep(SOURCE_LABELS[SOURCE_PLATFORM], "chosen", _name(snapshot, key)))
                break
    if not result.start:
        result.refusal = REFUSAL_NO_CANDIDATE
        result.refusal_detail = (
            "No model in the platform order is enabled, allowed in this Workspace and cleared for its data class."
        )
        return result

    result.chain = [result.start]
    if snapshot.fallback == "next":
        result.chain += [
            key for key in snapshot.order
            if key != result.start and not gate(snapshot.model(key), scope, capability=capability)
        ]
    return result


__all__ = [
    "ModelRequest",
    "REFUSAL_CHOICE_NOT_ALLOWED",
    "REFUSAL_NO_CANDIDATE",
    "Resolution",
    "SOURCE_LABELS",
    "TraceStep",
    "candidates",
    "resolve_model",
]
