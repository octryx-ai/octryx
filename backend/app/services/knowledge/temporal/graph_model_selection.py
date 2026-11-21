"""Which governed runtimes may serve graph extraction for one Workspace.

The choice is explicit, in this order, and never a silent pick of whatever target is first:

1. Control-plane runtimes tagged ``extract`` (``use_case_tags``): an operator routed graph extraction
   to a model on purpose. Only those are used, in their priority order.
2. Otherwise the Workspace's gateway alias admission policy (``Project.config["model_policy"]``,
   ``model_gateway/litellm/policy.py``). Only ``litellm_gateway`` runtimes the Workspace admits are
   used: first the aliases of ``allowed_aliases`` in that list's order, then, only under
   ``allow_all_admitted_aliases``, the other admitted aliases in runtime priority order. Admission
   (``admit_runtimes_for_dispatch``) decides which alias is admitted, so ``denied_aliases``, the level
   allowlist and the policy engine apply unchanged; ``model_alias_access_decision`` only tells an
   explicit grant from an allow-all one for the order. A direct provider target never serves this path.
3. Neither: ``needs_configuration`` / ``graph_model_unconfigured``. No model is called.

Every chain is admitted under the registered dispatch owner ``knowledge_temporal_graph`` for the one
Workspace the episode belongs to. Like admission, only the project row's own config is read. Every
refusal is a :class:`GraphModelUnavailableError` with a fixed state and reason.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...model_gateway.dispatch_admission import (
    REASON_CONTEXT_MISSING,
    REASON_CONTEXT_NOT_AUTHORIZED,
    REASON_CONTEXT_UNRESOLVABLE,
    admit_runtimes_for_dispatch,
)
from ...model_gateway.litellm.policy import (
    MODEL_POLICY_CONFIG_KEY,
    POLICY_REASON_ALLOW_ALL,
    POLICY_REASON_EXPLICIT_ALLOW,
    model_alias_access_decision,
)
from ...model_gateway.litellm.runtime_admission import runtime_uses_gateway_driver
from .errors import GraphModelUnavailableError

DISPATCH_OWNER = "knowledge_temporal_graph"
ROLE = "extract"
NEEDS_CONFIGURATION = "needs_configuration"
REASON_UNCONFIGURED = "graph_model_unconfigured"
REASON_NO_RUNTIME = "no_runtime_configured"
REASON_TAGGED_NOT_ADMITTED = "extract_runtime_not_admitted"
# The Workspace itself could not be resolved or admitted: its own refusal, not a missing grant.
_WORKSPACE_REFUSALS = frozenset({REASON_CONTEXT_MISSING, REASON_CONTEXT_NOT_AUTHORIZED, REASON_CONTEXT_UNRESOLVABLE})

RuntimeResolver = Callable[..., Awaitable[list[dict[str, Any]]]]


def _tagged(runtime: dict[str, Any]) -> bool:
    return ROLE in {str(tag).strip().lower() for tag in runtime.get("use_case_tags") or ()}


def _alias(runtime: dict[str, Any]) -> str:
    return str(runtime.get("model") or "").strip()


def _priority(runtime: dict[str, Any]) -> int:
    value = runtime.get("priority")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


async def _admitted_tagged(db: AsyncSession, tagged: list[dict[str, Any]], project_id: str) -> list[dict[str, Any]]:
    admission = await admit_runtimes_for_dispatch(db, tagged, project_ids=project_id, owner=DISPATCH_OWNER)
    if not admission.allowed:
        raise GraphModelUnavailableError(str(admission.state), str(admission.reason))
    dispatchable = list(admission.dispatchable_runtimes())
    if not dispatchable:
        raise GraphModelUnavailableError(NEEDS_CONFIGURATION, REASON_TAGGED_NOT_ADMITTED)
    return dispatchable


async def _project_config(db: AsyncSession, project_id: str) -> dict[str, Any]:
    from ....models import Project

    project = await db.get(Project, project_id)
    return dict(project.config or {}) if project is not None and isinstance(project.config, dict) else {}


def _policy_order(admitted: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    """Explicit grants in ``allowed_aliases`` order, then allow-all aliases in runtime priority order."""
    policy = config.get(MODEL_POLICY_CONFIG_KEY)
    allowed = policy.get("allowed_aliases") if isinstance(policy, dict) else None
    position: dict[str, int] = {}
    for index, alias in enumerate(allowed if isinstance(allowed, list) else []):
        position.setdefault(str(alias or "").strip(), index)
    granted: list[dict[str, Any]] = []
    allow_all: list[dict[str, Any]] = []
    for runtime in admitted:
        reason = model_alias_access_decision(_alias(runtime), config).reason
        if reason == POLICY_REASON_EXPLICIT_ALLOW:
            granted.append(runtime)
        elif reason == POLICY_REASON_ALLOW_ALL:
            allow_all.append(runtime)
    granted.sort(key=lambda runtime: (position.get(_alias(runtime), len(position)), _priority(runtime)))
    allow_all.sort(key=_priority)
    return granted + allow_all


async def _workspace_policy_runtimes(
    db: AsyncSession, project_id: str, runtimes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    gateway = [runtime for runtime in runtimes if runtime_uses_gateway_driver(runtime)]
    if not gateway:
        raise GraphModelUnavailableError(NEEDS_CONFIGURATION, REASON_UNCONFIGURED)
    admission = await admit_runtimes_for_dispatch(db, gateway, project_ids=project_id, owner=DISPATCH_OWNER)
    if not admission.allowed and admission.reason in _WORKSPACE_REFUSALS:
        raise GraphModelUnavailableError(str(admission.state), str(admission.reason))
    ordered = _policy_order(list(admission.dispatchable_runtimes()), await _project_config(db, project_id))
    if not ordered:
        raise GraphModelUnavailableError(NEEDS_CONFIGURATION, REASON_UNCONFIGURED)
    return ordered


async def select_graph_runtimes(
    db: AsyncSession,
    *,
    project_id: str,
    resolve_runtimes: RuntimeResolver | None = None,
) -> list[dict[str, Any]]:
    """The admitted runtimes for graph extraction in this Workspace, in order, or a fixed refusal."""
    if resolve_runtimes is None:
        from ...control_plane_service import resolve_control_plane_runtimes

        resolve_runtimes = resolve_control_plane_runtimes
    runtimes = await resolve_runtimes(db)
    if not runtimes:
        raise GraphModelUnavailableError(NEEDS_CONFIGURATION, REASON_NO_RUNTIME)
    tagged = [runtime for runtime in runtimes if _tagged(runtime)]
    if tagged:
        return await _admitted_tagged(db, tagged, project_id)
    return await _workspace_policy_runtimes(db, project_id, runtimes)


__all__ = [
    "DISPATCH_OWNER",
    "REASON_TAGGED_NOT_ADMITTED",
    "REASON_UNCONFIGURED",
    "ROLE",
    "select_graph_runtimes",
]
