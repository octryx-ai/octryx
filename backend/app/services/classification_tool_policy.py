"""The classification policy matrix at the tool admission: connector families and log reads. One decision, called by
every admission point of the chat and the MCP server."""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.data_classification.policy_rules import ACCESS_NONE, ACCESS_READ, CONNECTOR_FAMILIES

from ..tools.kubernetes_kubectl_argv import kubectl_is_read_only
from ..tools.kubernetes_kubectl_flags import parse_kubectl_args
from .data_classification.policy_matrix import load_classification_policy
from .data_classification.workspace_overrides import apply_overrides, stored_overrides
from .model_gateway.data_policy.classification import DATA_POLICY_CONFIG_KEY, resolve_data_classification

CLASSIFICATION_TOOL_POLICY_KEY = "classification_tool_policy"
POLICY_NAME = "classification_policy"

REASON_CONNECTOR_DENIED = "classification_connector_denied"
REASON_CONNECTOR_READ_ONLY = "classification_connector_read_only"
REASON_LOG_MASKING_NOT_AVAILABLE = "log_masking_not_available"
REASON_ALLOWED = "classification_policy_allows"
REASON_CEDAR_POLICY_DENIED = "cedar_policy_denied"  # = policy_engine.shadow.REASON_CEDAR_POLICY_DENIED

LOG_READING_TOOLS = frozenset({"get_pod_logs", "get_aws_ec2_logs", "get_aws_lambda_logs"})
_MESSAGES = {
    REASON_CONNECTOR_DENIED: "The Workspace's data classification does not allow the {family} connector.",
    REASON_CONNECTOR_READ_ONLY: "The Workspace's data classification allows the {family} connector read-only.",
    REASON_LOG_MASKING_NOT_AVAILABLE: (
        "The Workspace's data classification requires masking of sensitive data in logs, which is not available for "
        "log reads yet."
    ),
}


@dataclass(frozen=True, slots=True)
class ToolClassificationDecision:
    allowed: bool
    reason: str
    family: str | None = None
    level: str | None = None
    # Set when the Cedar policy engine (enforce mode) denies: the deciding policies and the log record.
    policy_ids: tuple[str, ...] = ()
    decision_id: str | None = None

    @property
    def message(self) -> str:
        if self.reason == REASON_CEDAR_POLICY_DENIED:
            policies = ", ".join(self.policy_ids) or "evaluation error"
            reference = f" Decision {self.decision_id}." if self.decision_id else ""
            return f"An Octryx policy denies this tool ({policies}).{reference}"
        return _MESSAGES.get(self.reason, "").format(family=self.family or "")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"allowed": self.allowed, "reason": self.reason, "family": self.family,
                                   "level": self.level}
        if self.reason == REASON_CEDAR_POLICY_DENIED:
            payload.update(policy_ids=list(self.policy_ids), decision_id=self.decision_id)
        return payload


@lru_cache(maxsize=1)
def _kubernetes_tool_names() -> frozenset[str]:
    from ..tools.definitions.kubernetes import get_kubernetes_definitions

    return frozenset(get_kubernetes_definitions())


def tool_connector_family(tool_name: str) -> str | None:
    if tool_name in _kubernetes_tool_names():
        return "kubernetes"
    from ..tools.definitions import get_tool_definition_metadata

    metadata = get_tool_definition_metadata(tool_name)
    connector = str(metadata.connector or "").strip().lower()
    return connector if metadata.owner_type == "connector" and connector in CONNECTOR_FAMILIES else None


def _kubectl_args(params: Mapping[str, Any] | None) -> list[str]:
    raw = (params or {}).get("args")
    if isinstance(raw, str):
        try:
            return shlex.split(raw)
        except ValueError:
            return raw.split()
    return [str(item) for item in raw] if isinstance(raw, list) else []


def _writes(tool_name: str, params: Mapping[str, Any] | None) -> bool:
    if tool_name == "run_kubectl":
        args = _kubectl_args(params)
        # Fail closed: anything that is not a read-only kubectl command counts as a write.
        return bool(args) and not kubectl_is_read_only(args)
    from ..tools.definitions import get_tool_definition_metadata

    metadata = get_tool_definition_metadata(tool_name)
    return metadata.risk in {"write", "admin"} or metadata.mutates_state or metadata.change_only


def _reads_logs(tool_name: str, params: Mapping[str, Any] | None) -> bool:
    if tool_name in LOG_READING_TOOLS:
        return True
    if tool_name == "run_kubectl":
        # The command kubectl resolves past any leading flags (``-n payments logs …``); ambiguous counts as logs.
        args = _kubectl_args(params)
        if not args:
            return False
        parsed = parse_kubectl_args(args)
        return parsed is None or (parsed.path[:1] == ["logs"])
    if tool_name == "aws_read_operation":
        return str((params or {}).get("service") or "").strip().lower() == "logs"
    return False


def builtin_tool_decision(
    name: str, section: Any, params: Mapping[str, Any] | None
) -> ToolClassificationDecision:
    if not isinstance(section, Mapping) or not section.get("level"):
        return ToolClassificationDecision(True, REASON_ALLOWED)
    level = str(section["level"])
    if section.get("log_masking_required") is True and _reads_logs(name, params):
        return ToolClassificationDecision(False, REASON_LOG_MASKING_NOT_AVAILABLE, tool_connector_family(name), level)
    family = tool_connector_family(name)
    if family is None:
        return ToolClassificationDecision(True, REASON_ALLOWED, None, level)
    access = (section.get("connectors") or {}).get(family)
    if access == ACCESS_NONE:
        return ToolClassificationDecision(False, REASON_CONNECTOR_DENIED, family, level)
    if access == ACCESS_READ and _writes(name, params):
        return ToolClassificationDecision(False, REASON_CONNECTOR_READ_ONLY, family, level)
    return ToolClassificationDecision(True, REASON_ALLOWED, family, level)


def _shadow_key(name: str, section: Any, params: Mapping[str, Any] | None) -> tuple | None:
    # Only listings are memoized; calls are evaluated every time.
    if params is not None:
        return None
    from .policy_engine.request_principal import principal_memo_key

    principal = principal_memo_key()  # Who-conditions make a listing decision per principal
    if not isinstance(section, Mapping) or not section.get("level"):
        return (name, None, principal)
    connectors = section.get("connectors") or {}
    return (name, str(section["level"]), str(section.get("workspace_id") or ""),
            tuple(sorted((str(key), str(value)) for key, value in connectors.items())),
            section.get("log_masking_required") is True, principal)


def classification_tool_decision(
    tool_name: str, project_config: Mapping[str, Any] | None, params: Mapping[str, Any] | None = None
) -> ToolClassificationDecision:
    # In shadow mode Cedar never changes this decision; in enforce mode a Cedar denial hides and refuses the tool.
    name = str(tool_name or "").strip()
    section = (project_config or {}).get(CLASSIFICATION_TOOL_POLICY_KEY) if project_config else None
    decision = builtin_tool_decision(name, section, params)
    from .named_connections.route_planner import planned_connection_ids
    from .policy_engine.points import POINT_TOOL_ADMISSION, tool_query
    from .policy_engine.shadow import LegacyDecision, enforced_denial, shadow_decision

    # A call's Cedar context names the connections it will run on; a listing names none.
    base = dict(project_config) if project_config else None
    connections = planned_connection_ids(name, dict(params), base) if params is not None else ()
    comparison = shadow_decision(
        POINT_TOOL_ADMISSION,
        LegacyDecision(decision.allowed, decision.reason),
        lambda: tool_query(name, section if isinstance(section, Mapping) else None, params, connections=connections),
        memo_key=_shadow_key(name, section, params),
    )
    denial = enforced_denial(decision.allowed, comparison)
    if denial is not None:
        return ToolClassificationDecision(False, REASON_CEDAR_POLICY_DENIED, decision.family, decision.level,
                                          denial.policy_ids, denial.decision_id)
    return decision


# The facts the Cedar policy engine receives for a tool (``policy_engine/points.tool_query``).
tool_writes = _writes
tool_reads_logs = _reads_logs


def classification_tool_refusal(
    tool_name: str, project_config: Mapping[str, Any] | None, params: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    decision = classification_tool_decision(tool_name, project_config, params)
    if decision.allowed:
        return None
    return {
        "error": decision.message,
        "tool_name": str(tool_name or "").strip(),
        "policy": POLICY_NAME,
        "reason": decision.reason,
        "policy_decision": decision.to_dict(),
    }


async def classification_tool_policy_section(
    db: AsyncSession, stored_config: Any, *, project_id: str | None = None
) -> dict[str, Any]:
    from .policy_engine.runtime import maintain_policy_runtime

    await maintain_policy_runtime()
    section = stored_config.get(DATA_POLICY_CONFIG_KEY) if isinstance(stored_config, Mapping) else None
    classification = resolve_data_classification(project_data_policy=section)
    if not classification.resolved:
        return {"level": None}
    # The level's rules met with the Workspace's stricter overrides.
    rules = apply_overrides((await load_classification_policy(db)).rules_for(classification.classification),
                            stored_overrides(stored_config))
    return {
        "level": classification.classification,
        "workspace_id": project_id,
        "connectors": {family: rules.connector_access(family) for family in CONNECTOR_FAMILIES},
        "log_masking_required": rules.log_masking_required,
    }


__all__ = [
    "CLASSIFICATION_TOOL_POLICY_KEY",
    "LOG_READING_TOOLS",
    "POLICY_NAME",
    "REASON_CONNECTOR_DENIED",
    "REASON_CONNECTOR_READ_ONLY",
    "REASON_LOG_MASKING_NOT_AVAILABLE",
    "ToolClassificationDecision",
    "classification_tool_decision",
    "classification_tool_policy_section",
    "classification_tool_refusal",
    "builtin_tool_decision",
    "tool_connector_family",
    "tool_reads_logs",
    "tool_writes",
]
