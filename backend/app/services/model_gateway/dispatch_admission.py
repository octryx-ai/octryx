"""Server-owned Workspace admission for every provider-dispatch boundary.

The main chat turn has a verified :class:`ProjectModelAdmission`. Without this
module every other dispatch owner receives the deny-everything singleton the
provider client-kwargs builder attaches, so it can only fail — usually swallowed
into a generic error. This module is the one door those owners go through.

What makes the admission trustworthy:

- **Policy comes from the row, never from the caller.** The resolver loads
  ``projects.config`` itself and reads only ``model_policy`` (the key registered
  to this owner in ``services/admin/project/admin_project_config_service.py``).
  No caller may pass a policy mapping, an allowed-alias list or a project config
  dict, so a request body or a model argument cannot widen admission.
- **The named project must exist and be active.** A caller supplies an *anchor*
  (a session's, work item's or config row's project id); the resolver verifies it
  against the row and denies otherwise. Where the anchor is user-supplied the
  owner also passes its authorized scope so the resolver can refuse a project the
  actor may not act for.
- **A multi-project scope is admitted by intersection.** Some owners legitimately
  span a Workspace plus its federated candidates. An alias is admitted only when
  *every* project in the scope admits it; the carried admission is the anchor
  project's real DB-derived admission, which by construction allows that alias.
  An empty scope is ``needs_configuration`` — it can never be an implicit allow.
- **Denials are values, not exceptions.** Every owner in the inventory already
  wrapped its dispatch in a broad ``except Exception``, so a typed exception would
  be swallowed exactly like today's generic failure. The boundary answers a
  :class:`DispatchAdmission` the caller has to branch on;
  :class:`DispatchAdmissionDeniedError` exists only for the owners whose contract is
  to raise, and carries the same bounded payload.
- **Non-gateway chains are untouched.** With no gateway runtime in the list the
  resolver returns the list unchanged and reads nothing from the database.

Registered owners live in :mod:`.dispatch_owners`; an unregistered owner key
cannot obtain an admission.
"""

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
    """Deduplicated project ids in caller order; the first one is the anchor."""

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
    """One owner's resolved Workspace scope and its alias decision function."""

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

    @property
    def driver_admission(self) -> ProjectModelAdmission | None:
        """Anchor admission carrying the strictest classification in the scope.

        Alias grants are intersected across the complete Workspace scope. Data
        policy must be at least as strict: one missing, unknown, or more-sensitive
        classification must survive into the driver's authoritative pre-dispatch
        gate instead of being hidden by a less-sensitive anchor Workspace.
        """

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
        """Admit an alias only when every project in the scope admits it."""

        normalized_alias = str(alias or "").strip()
        if not self.allowed:
            return ModelAliasAccessDecision(normalized_alias, False, self.reason)
        for admission in self.scope:
            decision = admission.decide(normalized_alias)
            if not decision.allowed:
                return decision
        return ModelAliasAccessDecision(normalized_alias, True, "")

    def evidence(self, *, alias: str = "", denial_reason: str = "") -> dict[str, Any]:
        """Bounded, allowlist-closed evidence about the *source* of a decision."""

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
    """The admission outcome for one owner's runtime list."""

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

    @property
    def partially_refused(self) -> bool:
        """Some gateway target was refused although the chain stayed dispatchable.

        The owner that exhausts such a chain must report the refusal too, instead
        of letting the last provider failure stand for the whole outcome.
        """

        return self.allowed and bool(self.reason)

    def dispatchable_runtimes(self) -> tuple[dict[str, Any], ...]:
        """Runtimes no policy owner refused, in the caller's priority order."""

        return tuple(runtime for runtime in self.runtimes if not runtime.get(ADMISSION_DENIAL_KEY))

    def first_dispatchable_runtime(self) -> dict[str, Any] | None:
        dispatchable = self.dispatchable_runtimes()
        return dispatchable[0] if dispatchable else None

    def to_result(self) -> dict[str, Any]:
        """The bounded, observable state an owner surfaces instead of swallowing.

        Nothing here is derived from a response body, a transport string, a
        configuration value or a secret: the reason is one of this module's
        constants and the evidence went through the gateway evidence allowlist.
        """

        result: dict[str, Any] = {"status": self.state, "dispatch_owner": self.owner}
        if self.reason:
            result["admission_reason"] = self.reason
        if self.evidence:
            result["admission_evidence"] = dict(self.evidence)
        if not self.allowed:
            result["dispatched"] = False
        return result


class DispatchAdmissionDeniedError(RuntimeError):
    """Typed denial for the owners whose contract is to raise.

    ``str(exc)`` is the fixed ``ALIAS_DENIED_MESSAGE`` constant, so nothing
    interpolated can leak through a traceback or a persisted runtime attempt; the
    state, reason and bounded evidence travel on the attached admission.
    """

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


async def resolve_workspace_admission(
    db: AsyncSession,
    *,
    project_ids: Any,
    owner: str,
    authorized_project_ids: Iterable[str] | None = None,
) -> WorkspaceAdmission:
    """Resolve one owner's Workspace scope from the project rows themselves.

    ``authorized_project_ids`` is passed by owners whose anchor comes from a user
    request; a project outside it is refused before any row is trusted.
    """

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
    """The existing ``admission_denial`` contract, so the engine needs no change."""

    anchor = workspace.anchor
    return build_alias_denial_annotation(
        decision=decision,
        project_admission_source=anchor.source if anchor else "",
        dispatch_owner=workspace.owner,
        project_scope_size=len(workspace.scope) or None,
    )


async def admit_runtimes_for_dispatch(
    db: AsyncSession,
    runtimes: Sequence[Mapping[str, Any]] | None,
    *,
    project_ids: Any,
    owner: str,
    authorized_project_ids: Iterable[str] | None = None,
) -> DispatchAdmission:
    """Admit or annotate one owner's runtime list before any client is built.

    Gateway targets are annotated rather than dropped, so a refusal stays visible
    in the turn's runtime attempts and a policy gap on one target cannot hard-fail
    a chain that still has admitted targets. Non-gateway targets pass through
    untouched, and a list without any gateway target reads nothing from the
    database.
    """

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


async def admit_client_kwargs_for_dispatch(
    db: AsyncSession,
    client_kwargs: Mapping[str, Any] | None,
    *,
    model: str | None,
    project_ids: Any,
    owner: str,
    authorized_project_ids: Iterable[str] | None = None,
) -> DispatchAdmission:
    """``admit_runtimes_for_dispatch`` for an owner that holds one client kwargs
    mapping plus a model rather than a resolved runtime chain.

    The alias is needed to decide, not to construct, so the returned runtime is
    the caller's own mapping: the boundary's ``model`` key is removed again unless
    the caller already had one. An owner that splats the result into
    ``get_provider`` therefore passes exactly the kwargs it passed before this
    boundary existed, which is what keeps every non-gateway driver unchanged.
    """

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
