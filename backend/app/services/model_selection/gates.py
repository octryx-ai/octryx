"""The model gates of one Workspace: may this catalog model answer here?

``CANDIDATES = enabled models ∩ Workspace allowed ∩ cleared for the Workspace's data class ∩ required capability``.
The same gates apply to every driver: a direct provider model (Bedrock, OpenRouter, Ollama) is bounded by the
Workspace allowlist and the data clearance exactly like a gateway alias. The gateway alias keeps its own admission
on top (project ``model_policy`` grant, alias catalog, Cedar ``call_model``), which reads the same clearance.

"Workspace allowed" includes that ``model_policy`` grant for a gateway alias (``model_alias_access_decision``, the
gateway admission's own rule) when the scope carries it: a model the gateway refuses is never chosen, named in the
chat's "Automatic · <model>" label or offered as the Workspace default.

Data class: a Workspace with a class needs a model cleared at or above it. A Workspace without a class (not set
yet) needs a model cleared for some data (at least ``public``): an uncleared model never answers anywhere.

Pure: the caller loads a ``SelectionSnapshot`` and a ``WorkspaceScope`` once and asks per model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..model_catalog.clearance import cleared_for
from ..model_catalog.contract import CAPABILITY_KEYS
from ..model_gateway.litellm.policy import MODEL_POLICY_CONFIG_KEY, model_alias_access_decision

GATEWAY_DRIVER = "litellm_gateway"

REASON_NOT_IN_CATALOG = "not_in_catalog"
REASON_NOT_ENABLED = "model_not_enabled"
REASON_PROVIDER_OFF = "provider_disabled"
REASON_NOT_ALLOWED = "not_allowed_in_workspace"
REASON_ALIAS_NOT_GRANTED = "alias_not_granted_in_workspace"
REASON_NOT_CLEARED = "not_cleared_for_data"
REASON_CAPABILITY = "capability_missing"
REASON_TEXT = {
    REASON_NOT_IN_CATALOG: "The model is not in the Model catalog.",
    REASON_NOT_ENABLED: "The model is not enabled in the Model catalog.",
    REASON_PROVIDER_OFF: "The model's provider connection is disabled.",
    REASON_NOT_ALLOWED: "The Workspace does not allow this model.",
    REASON_ALIAS_NOT_GRANTED: "The Workspace's model policy does not grant this company-gateway model.",
    REASON_NOT_CLEARED: "The model is not cleared for the Workspace's data class.",
    REASON_CAPABILITY: "The model lacks a capability the workflow requires.",
}


@dataclass(frozen=True, slots=True)
class CatalogModel:
    key: str
    provider_id: str
    model_id: str
    display_name: str
    provider_name: str
    driver: str
    enabled: bool
    provider_active: bool
    cleared_up_to: str | None
    capabilities: dict[str, bool]
    target_ids: tuple[str, ...] = ()
    target_tags: tuple[str, ...] = ()

    @property
    def is_gateway(self) -> bool:
        return self.driver == GATEWAY_DRIVER


@dataclass(frozen=True, slots=True)
class AliasGrant:
    """A Workspace's ``projects.config.model_policy``, frozen: which company-gateway aliases it grants."""

    allowed: frozenset[str] = frozenset()
    denied: frozenset[str] = frozenset()
    allow_all: bool = False

    @classmethod
    def from_policy(cls, policy: Any) -> AliasGrant:
        source = policy if isinstance(policy, dict) else {}

        def aliases(value: Any) -> frozenset[str]:
            return frozenset(str(item) for item in value) if isinstance(value, list) else frozenset()

        return cls(
            allowed=aliases(source.get("allowed_aliases")),
            denied=aliases(source.get("denied_aliases")),
            allow_all=source.get("allow_all_admitted_aliases") is True,
        )

    def grants(self, alias: str) -> bool:
        policy = {
            "allowed_aliases": sorted(self.allowed),
            "denied_aliases": sorted(self.denied),
            "allow_all_admitted_aliases": self.allow_all,
        }
        return model_alias_access_decision(alias, {MODEL_POLICY_CONFIG_KEY: policy}).allowed


@dataclass(frozen=True, slots=True)
class WorkspaceScope:
    workspace_id: str = ""
    data_class: str = ""
    # ``selected_only``: only these runtime targets (their models) are allowed; ``all_installed``: every model.
    assignment_mode: str = "all_installed"
    selected_target_ids: frozenset[str] = field(default_factory=frozenset)
    default_target_id: str = ""
    # The Workspace's own model per background task (``projects.config.model_task_overrides``, written by
    # Workspace → Models): ``((task, catalog_key), …)``; a task without an entry uses the platform task model.
    task_overrides: tuple[tuple[str, str], ...] = ()
    # The Workspace's ``model_policy`` grant for gateway aliases; ``None`` when the caller did not load the Workspace
    # config (the gateway admission still decides on dispatch).
    alias_grant: AliasGrant | None = None


def allowed_in_workspace(model: CatalogModel, scope: WorkspaceScope) -> bool:
    if scope.assignment_mode != "selected_only":
        return True
    return any(target_id in scope.selected_target_ids for target_id in model.target_ids)


def alias_granted(model: CatalogModel, scope: WorkspaceScope) -> bool:
    return not model.is_gateway or scope.alias_grant is None or scope.alias_grant.grants(model.model_id)


def cleared_for_workspace(model: CatalogModel, scope: WorkspaceScope) -> bool:
    return cleared_for(model.cleared_up_to, scope.data_class or "public")


def meets_capability(model: CatalogModel, capability: str) -> bool:
    """Catalog capabilities are explicit (no name heuristic); another catalog key reads the target tags."""
    if not capability:
        return True
    if capability in CAPABILITY_KEYS:
        return bool(model.capabilities.get(capability))
    return capability in model.target_tags


def gate(model: CatalogModel | None, scope: WorkspaceScope, *, capability: str = "") -> str:
    """The first reason the model may not answer in this Workspace, or ``""``."""
    if model is None:
        return REASON_NOT_IN_CATALOG
    if not model.enabled:
        return REASON_NOT_ENABLED
    if not model.provider_active:
        return REASON_PROVIDER_OFF
    if not allowed_in_workspace(model, scope):
        return REASON_NOT_ALLOWED
    if not alias_granted(model, scope):
        return REASON_ALIAS_NOT_GRANTED
    if not cleared_for_workspace(model, scope):
        return REASON_NOT_CLEARED
    if not meets_capability(model, capability):
        return REASON_CAPABILITY
    return ""


def reason_text(reason: str) -> str:
    return REASON_TEXT.get(reason, "The model may not answer here.")


def capabilities_from(value: Any) -> dict[str, bool]:
    raw = value if isinstance(value, dict) else {}
    return {key: bool(raw.get(key)) for key in CAPABILITY_KEYS}


__all__ = [
    "AliasGrant",
    "CatalogModel",
    "GATEWAY_DRIVER",
    "REASON_ALIAS_NOT_GRANTED",
    "REASON_CAPABILITY",
    "REASON_NOT_ALLOWED",
    "REASON_NOT_CLEARED",
    "REASON_NOT_ENABLED",
    "REASON_NOT_IN_CATALOG",
    "REASON_PROVIDER_OFF",
    "WorkspaceScope",
    "alias_granted",
    "allowed_in_workspace",
    "capabilities_from",
    "cleared_for_workspace",
    "gate",
    "meets_capability",
    "reason_text",
]
