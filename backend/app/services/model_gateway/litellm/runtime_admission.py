"""Project admission for resolved gateway runtime targets, before any request."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runtime.runtime_admission_contract import RUNTIME_ADMISSION_DENIAL_KEY
from app.agent.runtime.runtime_errors import (
    RUNTIME_ERROR_ALIAS_DENIED,
    RUNTIME_ERROR_DATA_POLICY_DENIED,
)

from ...data_classification.policy_matrix import model_allowlists
from ..data_policy import (
    UNRESOLVED_DATA_CLASSIFICATION,
    DataPolicyDecision,
    WorkspaceDataClassification,
    resolve_workspace_data_classification,
)
from .admission_types import AdmissionDenial
from .alias_catalog import resolve_alias_admission
from .errors import GATEWAY_STATE_ALIAS_DENIED, GATEWAY_STATE_DATA_POLICY_DENIED
from .evidence import build_denial_evidence
from .policy import ModelAliasAccessDecision
from .project_admission import (
    PROJECT_ADMISSION_KWARG,
    ProjectModelAdmission,
    build_project_model_admission,
)

ADMISSION_DENIAL_KEY = RUNTIME_ADMISSION_DENIAL_KEY
LITELLM_GATEWAY_DRIVER = "litellm_gateway"

# Fixed user/audit messages. They name the alias only — never the project, the
# upstream model group, the classification, or the policy contents.
ALIAS_DENIED_MESSAGE = "Model alias is not granted for this project."
DATA_POLICY_DENIED_MESSAGE = "Workspace data classification is not permitted for this model alias."

ADMISSION_SOURCE_AGENT_RUN = "prepare_agent_run"


def runtime_uses_gateway_driver(runtime: Any) -> bool:
    if not isinstance(runtime, dict):
        return False
    driver = str(runtime.get("driver") or runtime.get("provider_name") or "").strip().lower()
    return driver == LITELLM_GATEWAY_DRIVER


# Shared by every producer, so the engine reads one shape and the evidence allowlist is applied in one place.
def build_alias_denial_annotation(
    *,
    decision: ModelAliasAccessDecision,
    project_admission_source: str,
    dispatch_owner: str = "",
    project_scope_size: int | None = None,
) -> AdmissionDenial:
    return {
        "error_class": RUNTIME_ERROR_ALIAS_DENIED,
        "reason": decision.reason,
        "message": ALIAS_DENIED_MESSAGE,
        "evidence": build_denial_evidence(
            gateway_state=GATEWAY_STATE_ALIAS_DENIED,
            denial_reason=decision.reason,
            alias=decision.alias,
            project_admission_source=project_admission_source,
            dispatch_owner=dispatch_owner,
            project_scope_size=project_scope_size,
        ),
    }


def build_data_policy_denial_annotation(
    *,
    decision: DataPolicyDecision,
    alias: str,
    project_admission_source: str,
    dispatch_owner: str = "",
    project_scope_size: int | None = None,
) -> AdmissionDenial:
    return {
        "error_class": RUNTIME_ERROR_DATA_POLICY_DENIED,
        "reason": decision.reason,
        "message": DATA_POLICY_DENIED_MESSAGE,
        "evidence": build_denial_evidence(
            gateway_state=GATEWAY_STATE_DATA_POLICY_DENIED,
            denial_reason=decision.reason,
            alias=alias,
            project_admission_source=project_admission_source,
            dispatch_owner=dispatch_owner,
            project_scope_size=project_scope_size,
            data_policy=decision.evidence(),
        ),
    }


def _admitted_runtime(runtime: dict[str, Any], admission: ProjectModelAdmission) -> dict[str, Any]:
    alias = str(runtime.get("model") or "").strip()
    decision = admission.decide(alias)
    if not decision.allowed:
        return {
            **runtime,
            ADMISSION_DENIAL_KEY: build_alias_denial_annotation(
                decision=decision,
                project_admission_source=admission.source,
            ),
        }
    # The provider catalog is read here, from the runtime's own resolved
    # provider config, so an alias whose declared data-policy class cannot be
    # established never reaches a client. ``resolve_alias_admission`` returns
    # its own fixed code, which is more useful than a generic "unknown".
    catalog = resolve_alias_admission(alias, runtime.get("config_json"))
    if catalog.entry is None:
        catalog_decision = ModelAliasAccessDecision(alias, False, catalog.denial_reason)
        return {
            **runtime,
            ADMISSION_DENIAL_KEY: build_alias_denial_annotation(
                decision=catalog_decision,
                project_admission_source=admission.source,
            ),
        }
    data_decision = admission.decide_data_policy(catalog.entry.data_policy_class)
    if not data_decision.allowed:
        return {
            **runtime,
            ADMISSION_DENIAL_KEY: build_data_policy_denial_annotation(
                decision=data_decision,
                alias=decision.alias,
                project_admission_source=admission.source,
            ),
        }
    # The driver re-checks alias and classification against this same
    # admission, so the grant is carried rather than implied by the runtime's
    # presence.
    return {**runtime, PROJECT_ADMISSION_KWARG: admission}


def apply_model_policy_to_runtimes(
    runtimes: list[dict[str, Any]] | None,
    *,
    project_config: dict[str, Any] | None,
    project_id: Any,
    data_classification: WorkspaceDataClassification = UNRESOLVED_DATA_CLASSIFICATION,
    source: str = ADMISSION_SOURCE_AGENT_RUN,
    level_model_aliases: Mapping[str, frozenset[str]] | None = None,
) -> list[dict[str, Any]]:
    """Admit or annotate the gateway runtimes for one server-owned project; without ``project_id`` every gateway
    target is denied. Non-gateway runtimes are returned untouched."""

    if not runtimes:
        return list(runtimes or [])
    admission = build_project_model_admission(
        project_id=project_id,
        project_config=project_config,
        source=source,
        data_classification=data_classification,
        level_model_aliases=level_model_aliases,
    )
    admitted: list[dict[str, Any]] = []
    for runtime in runtimes:
        if not runtime_uses_gateway_driver(runtime):
            admitted.append(runtime)
            continue
        admitted.append(_admitted_runtime(runtime, admission))
    return admitted


async def admit_gateway_runtimes(
    db: AsyncSession,
    runtimes: list[dict[str, Any]] | None,
    *,
    project_config: dict[str, Any] | None,
    project_id: Any,
    session_metadata: dict[str, Any] | None = None,
    source: str = ADMISSION_SOURCE_AGENT_RUN,
) -> list[dict[str, Any]]:
    """Resolve the server-owned classification, then admit the runtime chain (the seam run preparation calls)."""

    if not runtimes or not any(runtime_uses_gateway_driver(runtime) for runtime in runtimes):
        return list(runtimes or [])

    return apply_model_policy_to_runtimes(
        runtimes,
        project_config=project_config,
        project_id=project_id,
        data_classification=await resolve_workspace_data_classification(
            db,
            project_id=project_id,
            session_metadata=session_metadata,
        ),
        source=source,
        level_model_aliases=await model_allowlists(db),
    )


__all__ = [
    "ADMISSION_DENIAL_KEY",
    "ADMISSION_SOURCE_AGENT_RUN",
    "ALIAS_DENIED_MESSAGE",
    "DATA_POLICY_DENIED_MESSAGE",
    "LITELLM_GATEWAY_DRIVER",
    "admit_gateway_runtimes",
    "apply_model_policy_to_runtimes",
    "build_alias_denial_annotation",
    "build_data_policy_denial_annotation",
    "runtime_uses_gateway_driver",
]
