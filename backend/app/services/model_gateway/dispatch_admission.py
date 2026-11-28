"""Server-owned Workspace admission for every provider-dispatch owner (registered in dispatch_owners)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models.project.project import Project
from ..data_classification.policy_matrix import model_allowlists
from .data_policy import DATA_POLICY_CONFIG_KEY, resolve_data_classification
from .dispatch_owner_record import DISPATCH_MODE_ADMITTED
from .dispatch_owners import dispatch_owner
from .litellm.errors import GATEWAY_STATE_ALIAS_DENIED
from .litellm.evidence import build_denial_evidence
from .litellm.policy import ModelAliasAccessDecision
from .litellm.project_admission import (
    PROJECT_ADMISSION_KWARG,
    ProjectModelAdmission,
    build_project_model_admission,
)
from .litellm.runtime_admission import (
    ADMISSION_DENIAL_KEY,
    ALIAS_DENIED_MESSAGE,
    build_alias_denial_annotation,
    runtime_uses_gateway_driver,
)

DISPATCH_STATE_ALLOWED = "allowed"
DISPATCH_STATE_DENIED = "denied"
DISPATCH_STATE_NEEDS_CONFIGURATION = "needs_configuration"

# No Workspace was named at all. That is a configuration gap in the owner, not a
# policy decision, so it gets the state an operator can act on.
REASON_CONTEXT_MISSING = "project_context_missing"
# A Workspace was named but does not exist or is inactive.
REASON_CONTEXT_UNRESOLVABLE = "project_context_unresolvable"
# A Workspace was named outside the actor's authorized scope.
REASON_CONTEXT_NOT_AUTHORIZED = "project_context_not_authorized"
# Every gateway target in the chain was refused and nothing else could serve.
REASON_NO_ADMITTED_RUNTIME = "no_admitted_gateway_runtime"

_REASON_STATES = {
    REASON_CONTEXT_MISSING: DISPATCH_STATE_NEEDS_CONFIGURATION,
    REASON_CONTEXT_UNRESOLVABLE: DISPATCH_STATE_DENIED,
    REASON_CONTEXT_NOT_AUTHORIZED: DISPATCH_STATE_DENIED,
}


def _normalized_scope(project_ids: Any) -> tuple[str, ...]:
    if project_ids is None:
        return ()
    if isinstance(project_ids, str):
        candidates: Iterable[Any] = [project_ids]
    elif isinstance(project_ids, Sequence):
        candidates = project_ids
    else:
        candidates = [project_ids]
    scope: list[str] = []
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if normalized and normalized not in scope:
            scope.append(normalized)
    return tuple(scope)


@dataclass(frozen=True, slots=True)
class WorkspaceAdmission:
    state: str
    owner: str
    reason: str = ""
    # Ordered as the caller's scope was; ``scope[0]`` is the anchor whose
    # admission is carried to the driver.
    scope: tuple[ProjectModelAdmission, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.state == DISPATCH_STATE_ALLOWED

    @property
    def anchor(self) -> ProjectModelAdmission | None:
        return self.scope[0] if self.scope else None

    # Alias grants intersect across the whole scope; the strictest classification of the scope (missing, unknown or more
    # sensitive) must reach the driver's gate, never hidden by a less sensitive anchor.
    @property
    def driver_admission(self) -> ProjectModelAdmission | None:
        anchor = self.anchor
        if anchor is None:
            return None
        classifications = [item.data_classification for item in self.scope]
        unresolved = next((item for item in classifications if not item.resolved), None)
        effective = unresolved or max(
            classifications,
            key=lambda item: item.rank if item.rank is not None else -1,
        )
        if effective is anchor.data_classification:
            return anchor
        return replace(anchor, data_classification=effective)

    def decide(self, alias: str | None) -> ModelAliasAccessDecision:
        normalized_alias = str(alias or "").strip()
        if not self.allowed:
            return ModelAliasAccessDecision(normalized_alias, False, self.reason)
        for admission in self.scope:
            decision = admission.decide(normalized_alias)
            if not decision.allowed:
                return decision
        return ModelAliasAccessDecision(normalized_alias, True, "")

    def evidence(self, *, alias: str = "", denial_reason: str = "") -> dict[str, Any]:
        anchor = self.anchor
        return build_denial_evidence(
            gateway_state=GATEWAY_STATE_ALIAS_DENIED,
            denial_reason=denial_reason,
            alias=alias,
            project_admission_source=anchor.source if anchor else "",
            dispatch_owner=self.owner,
            project_scope_size=len(self.scope) or None,
        )


@dataclass(frozen=True, slots=True)
class DispatchAdmission:
    state: str
    owner: str
    runtimes: tuple[dict[str, Any], ...] = ()
    reason: str = ""
    evidence: Mapping[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.state == DISPATCH_STATE_ALLOWED

    @property
    def needs_configuration(self) -> bool:
        return self.state == DISPATCH_STATE_NEEDS_CONFIGURATION

    # An owner that exhausts such a chain reports the refusal too, so the last provider failure does not stand for the
    # whole outcome.
    @property
    def partially_refused(self) -> bool:
        return self.allowed and bool(self.reason)

    def dispatchable_runtimes(self) -> tuple[dict[str, Any], ...]:
        return tuple(runtime for runtime in self.runtimes if not runtime.get(ADMISSION_DENIAL_KEY))

    def first_dispatchable_runtime(self) -> dict[str, Any] | None:
        dispatchable = self.dispatchable_runtimes()
        return dispatchable[0] if dispatchable else None

    # Nothing derived from a response body, a transport string, a configuration value or a secret: a reason constant and
    # allowlist-closed evidence.
    def to_result(self) -> dict[str, Any]:
        result: dict[str, Any] = {"status": self.state, "dispatch_owner": self.owner}
        if self.reason:
            result["admission_reason"] = self.reason
        if self.evidence:
            result["admission_evidence"] = dict(self.evidence)
        if not self.allowed:
            result["dispatched"] = False
        return result


# str(exc) is the fixed ALIAS_DENIED_MESSAGE, so nothing interpolated leaks through a traceback or a persisted runtime
# attempt.
class DispatchAdmissionDeniedError(RuntimeError):
    def __init__(self, admission: DispatchAdmission):
        super().__init__(ALIAS_DENIED_MESSAGE)
        self.admission = admission

    @property
    def state(self) -> str:
        return self.admission.state

    @property
    def reason(self) -> str:
        return self.admission.reason

    def to_result(self) -> dict[str, Any]:
        return self.admission.to_result()


# Owners whose anchor comes from a user request pass authorized_project_ids; a project outside it is refused before any
# row is trusted.
async def resolve_workspace_admission(
    db: AsyncSession,
    *,
    project_ids: Any,
    owner: str,
    authorized_project_ids: Iterable[str] | None = None,
) -> WorkspaceAdmission:
    registered = dispatch_owner(owner)
    if registered.mode != DISPATCH_MODE_ADMITTED:
        raise ValueError(
            f"Dispatch owner '{registered.key}' is registered as '{registered.mode}' and must not "
            "resolve a Workspace admission."
        )
    scope_ids = _normalized_scope(project_ids)
    # No scope, or no session to resolve it against: either way no project row can
    # be read, so no policy exists to evaluate. That is a configuration gap.
    if not scope_ids or db is None:
        return WorkspaceAdmission(
            state=DISPATCH_STATE_NEEDS_CONFIGURATION,
            owner=registered.key,
            reason=REASON_CONTEXT_MISSING,
        )
    if authorized_project_ids is not None:
        authorized = {str(item or "").strip() for item in authorized_project_ids}
        if any(project_id not in authorized for project_id in scope_ids):
            return WorkspaceAdmission(
                state=DISPATCH_STATE_DENIED,
                owner=registered.key,
                reason=REASON_CONTEXT_NOT_AUTHORIZED,
            )
    admissions: list[ProjectModelAdmission] = []
    level_model_aliases = await model_allowlists(db)
    for project_id in scope_ids:
        project = await db.get(Project, project_id)
        if project is None or not project.is_active:
            return WorkspaceAdmission(
                state=DISPATCH_STATE_DENIED,
                owner=registered.key,
                reason=REASON_CONTEXT_UNRESOLVABLE,
            )
        # Only the row's own config is read. Neither model admission nor data
        # classification can be contributed by a merged turn config, knowledge
        # map, tool config, or request body.
        project_config = dict(project.config or {})
        admissions.append(
            build_project_model_admission(
                project_id=project.id,
                project_config=project_config,
                source=registered.key,
                data_classification=resolve_data_classification(
                    project_data_policy=project_config.get(DATA_POLICY_CONFIG_KEY),
                ),
                level_model_aliases=level_model_aliases,
            )
        )
    return WorkspaceAdmission(
        state=DISPATCH_STATE_ALLOWED,
        owner=registered.key,
        scope=tuple(admissions),
    )


def _denial_annotation(workspace: WorkspaceAdmission, decision: ModelAliasAccessDecision) -> dict[str, Any]:
    anchor = workspace.anchor
    return build_alias_denial_annotation(
        decision=decision,
        project_admission_source=anchor.source if anchor else "",
        dispatch_owner=workspace.owner,
        project_scope_size=len(workspace.scope) or None,
    )


# Gateway targets are annotated, never dropped: a refusal stays visible in the runtime attempts and one refused target
# cannot fail a chain that still has admitted ones.
async def admit_runtimes_for_dispatch(
    db: AsyncSession,
    runtimes: Sequence[Mapping[str, Any]] | None,
    *,
    project_ids: Any,
    owner: str,
    authorized_project_ids: Iterable[str] | None = None,
) -> DispatchAdmission:
    registered = dispatch_owner(owner)
    normalized = [dict(runtime) for runtime in (runtimes or []) if isinstance(runtime, Mapping)]
    if not any(runtime_uses_gateway_driver(runtime) for runtime in normalized):
        return DispatchAdmission(
            state=DISPATCH_STATE_ALLOWED,
            owner=registered.key,
            runtimes=tuple(normalized),
        )

    workspace = await resolve_workspace_admission(
        db,
        project_ids=project_ids,
        owner=owner,
        authorized_project_ids=authorized_project_ids,
    )
    admitted: list[dict[str, Any]] = []
    first_denial: ModelAliasAccessDecision | None = None
    for runtime in normalized:
        if not runtime_uses_gateway_driver(runtime):
            admitted.append(runtime)
            continue
        decision = workspace.decide(str(runtime.get("model") or ""))
        if decision.allowed:
            # Carry the anchor's admission so the driver re-checks the alias at
            # its own boundary instead of trusting the chain's presence.
            admitted.append({**runtime, PROJECT_ADMISSION_KWARG: workspace.driver_admission})
            continue
        first_denial = first_denial or decision
        admitted.append({**runtime, ADMISSION_DENIAL_KEY: _denial_annotation(workspace, decision)})

    dispatchable = any(not runtime.get(ADMISSION_DENIAL_KEY) for runtime in admitted)
    if first_denial is not None:
        reason = first_denial.reason
    elif dispatchable:
        reason = ""
    else:
        reason = REASON_NO_ADMITTED_RUNTIME
    return DispatchAdmission(
        # A chain that still has an admitted target is allowed, but it keeps the
        # refusal it carries: an owner whose admitted targets then fail must be
        # able to report the policy refusal instead of only the provider error.
        state=DISPATCH_STATE_ALLOWED if dispatchable else _REASON_STATES.get(reason, DISPATCH_STATE_DENIED),
        owner=registered.key,
        runtimes=tuple(admitted),
        reason=reason,
        evidence=(
            workspace.evidence(
                alias=first_denial.alias if first_denial else "",
                denial_reason=reason,
            )
            if reason
            else {}
        ),
    )


# The boundary's model key is removed again unless the caller had one, so a splat into get_provider passes exactly the
# caller's kwargs and non-gateway drivers stay unchanged.
async def admit_client_kwargs_for_dispatch(
    db: AsyncSession,
    client_kwargs: Mapping[str, Any] | None,
    *,
    model: str | None,
    project_ids: Any,
    owner: str,
    authorized_project_ids: Iterable[str] | None = None,
) -> DispatchAdmission:
    caller_kwargs = dict(client_kwargs or {})
    admission = await admit_runtimes_for_dispatch(
        db,
        [{**caller_kwargs, "model": str(model or "").strip()}],
        project_ids=project_ids,
        owner=owner,
        authorized_project_ids=authorized_project_ids,
    )
    if "model" in caller_kwargs:
        return admission
    return _without_runtime_key(admission, "model")


def _without_runtime_key(admission: DispatchAdmission, key: str) -> DispatchAdmission:
    return DispatchAdmission(
        state=admission.state,
        owner=admission.owner,
        runtimes=tuple({k: v for k, v in runtime.items() if k != key} for runtime in admission.runtimes),
        reason=admission.reason,
        evidence=admission.evidence,
    )


__all__ = [
    "DISPATCH_STATE_ALLOWED",
    "DISPATCH_STATE_DENIED",
    "DISPATCH_STATE_NEEDS_CONFIGURATION",
    "REASON_CONTEXT_MISSING",
    "REASON_CONTEXT_NOT_AUTHORIZED",
    "REASON_CONTEXT_UNRESOLVABLE",
    "REASON_NO_ADMITTED_RUNTIME",
    "DispatchAdmission",
    "DispatchAdmissionDeniedError",
    "WorkspaceAdmission",
    "admit_client_kwargs_for_dispatch",
    "admit_runtimes_for_dispatch",
    "resolve_workspace_admission",
]
