"""The three-layer alias admission every gateway dispatch goes through.

Shared by the governed driver (``agent/providers/litellm_gateway.py``) and the
inbound Anthropic Messages route (``services/model_gateway/inbound``), so both
doors refuse exactly the same aliases for exactly the same reasons:

1. the project must have granted the alias (checked first, so a project without
   a grant learns nothing about the provider catalog);
2. the provider alias catalog must admit it;
3. the Workspace's server-owned data classification must be covered by the
   alias' declared ``data_policy_class``.

Every denial is a typed, fixed-message :class:`LiteLLMGatewayError` raised
before any request payload exists, so a denial costs nothing.
"""

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
    """Return the admitted catalog entry and the permitted data-policy decision."""

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
