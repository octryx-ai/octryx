"""The three-layer alias admission every gateway dispatch goes through: project grant, catalog, data policy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..data_policy import DataPolicyDecision
from .alias_catalog import GATEWAY_CONFIG_KEY, AliasEntry, resolve_alias_admission
from .errors import GATEWAY_STATE_ALIAS_DENIED, GATEWAY_STATE_DATA_POLICY_DENIED, LiteLLMGatewayError
from .project_admission import ProjectModelAdmission


def admitted_alias_entry(
    project_admission: ProjectModelAdmission,
    alias: str,
    gateway_section: Mapping[str, Any],
) -> tuple[AliasEntry, DataPolicyDecision]:
    decision = project_admission.decide(alias)
    if not decision.allowed:
        raise LiteLLMGatewayError(GATEWAY_STATE_ALIAS_DENIED, denial_reason=decision.reason) from None
    admission = resolve_alias_admission(alias, {GATEWAY_CONFIG_KEY: dict(gateway_section)})
    if admission.entry is None:
        raise LiteLLMGatewayError(GATEWAY_STATE_ALIAS_DENIED, denial_reason=admission.denial_reason) from None
    data_decision = project_admission.decide_data_policy(admission.entry.data_policy_class)
    if not data_decision.allowed:
        raise LiteLLMGatewayError(GATEWAY_STATE_DATA_POLICY_DENIED, denial_reason=data_decision.reason) from None
    return admission.entry, data_decision


__all__ = ["admitted_alias_entry"]
