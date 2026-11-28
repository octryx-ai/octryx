"""One Cedar query per enforcement point, built from the inputs the existing decision received."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.services.data_classification.policy_rules import LevelRules

from ..agent_gateway.seat_policy_keys import REQUIRES_GOVERNED_KEY, SEAT_MODE_FORBIDDEN, SEAT_MODE_KEY
from ..model_gateway.data_policy.classification import (
    MODEL_DATA_POLICY_CLASSES,
    WorkspaceDataClassification,
    classification_rank,
    normalized_classification,
)
from .cedar_text import render
from .engine import CedarRequest, EntityRef, entity_value
from .entities import (
    model_alias_entity,
    principal_entities,
    remote_model_entity,
    tool_entity,
    workspace_entity,
)
from .schema import (
    ACTION_CALL_MODEL,
    ACTION_CALL_TOOL,
    ACTION_READ_CONNECTOR,
    ACTION_USE_REMOTE_EMBEDDINGS,
    ACTION_USE_RERANKER,
    ACTION_USE_SEAT,
    ACTION_WRITE_CONNECTOR,
    ROUTE_GOVERNED,
)
from .translator import (
    FAMILY_MODEL,
    FAMILY_REMOTE,
    FAMILY_SEAT,
    FAMILY_TOOL,
    model_level_policies,
    platform_policies,
    remote_level_policies,
    seat_level_policies,
    tool_level_policies,
    workspace_model_policies,
)

POINT_SEAT = "seat"
POINT_MODEL_ADMISSION = "model_admission"
POINT_REMOTE_MODEL = "remote_model"
POINT_TOOL_ADMISSION = "tool_admission"
POINT_GATEWAY_TOOL_CHECK = "gateway_tool_check"
# A tool result before it enters a model's context (``content_points.tool_result_query``).
POINT_TOOL_RESULT = "tool_result"
POINT_DEVICE_DISPATCH = "device_dispatch"  # the query lives in ``device_point``
POINTS: tuple[str, ...] = (
    POINT_SEAT, POINT_MODEL_ADMISSION, POINT_REMOTE_MODEL, POINT_TOOL_ADMISSION, POINT_GATEWAY_TOOL_CHECK,
    POINT_TOOL_RESULT, POINT_DEVICE_DISPATCH,
)

REMOTE_KIND_RERANKER = "reranker"


# A principal and its entities (``entities.principal_entities`` / ``principals.load_principal``). A point given
# none uses the request's bound principal (``request_principal``); outside any request it is ``User::"unknown"``.
Principal = tuple[EntityRef, list[Mapping[str, Any]]]


# ``context.content`` of a decision that carries no content (the content-free admission of an alias).
EMPTY_CONTENT: Mapping[str, Any] = {"scanned": False, "complete": True, "detected": [], "categories": [],
                                    "findings": 0, "sources": []}


def alias_approved_for(alias: str) -> frozenset[str]:
    from .runtime import current_runtime

    return frozenset(current_runtime().alias_approvals.get(alias, frozenset()))


def _bound_principal() -> Principal:
    from .request_principal import current_principal

    return current_principal() or principal_entities(None)


@dataclass(frozen=True, slots=True)
class PointQuery:
    point: str
    action: str
    workspace_id: str
    principal: EntityRef
    resource: str
    policies: str
    requests: tuple[CedarRequest, ...]
    entities: tuple[Mapping[str, Any], ...]
    # What the decision log stores instead of ``resource`` (empty: ``resource`` is safe to store).
    log_resource: str = ""
    # Content points: the scan summary the decision log stores (names and counts only), the requests the
    # draft shadow asks instead (the scan with the draft's custom detectors), and whether a denial is recorded
    # even when the existing check agrees (a blocked request is worth reading).
    log_content: Mapping[str, Any] | None = None
    draft_requests: tuple[CedarRequest, ...] | None = None
    record_denials: bool = False
    # False: the caller writes the request's one decision record with this decision in it (the gateway and the
    # model-call wrapper, I-4), so the comparison writes none of its own.
    recorded: bool = True


def _query(point: str, action: str, workspace: EntityRef, principal: EntityRef, resource: str, policies: list,
           requests: list[CedarRequest], entities: list[Mapping[str, Any]], *, log_resource: str = "") -> PointQuery:
    return PointQuery(point, action, workspace.id, principal, resource, render(policies), tuple(requests),
                      tuple(entities), log_resource)


def seat_query(
    *, workspace_id: str | None, level: str | None, rules: LevelRules | None, raw_policy: Mapping[str, Any],
    user_id: str | None = None, principal: Principal | None = None,
) -> PointQuery:
    resolved = level if rules is not None and level else None
    workspace, workspace_record = workspace_entity(
        workspace_id, classification=resolved, classification_rank=classification_rank(resolved),
        seat_mode=str(raw_policy.get(SEAT_MODE_KEY, SEAT_MODE_FORBIDDEN)),
        requires_governed_routing=raw_policy.get(REQUIRES_GOVERNED_KEY) is True,
    )
    principal, principal_records = principal or (principal_entities(user_id) if user_id else None) \
        or _bound_principal()
    policies = platform_policies([FAMILY_SEAT])
    if resolved and rules is not None:
        policies += seat_level_policies(resolved, seat_allowed=rules.seat_allowed,
                                        requires_governed_routing=rules.requires_governed_routing)
    request = CedarRequest(principal, ACTION_USE_SEAT, workspace, {"workspace": entity_value(workspace)})
    return _query(POINT_SEAT, ACTION_USE_SEAT, workspace, principal, workspace.label(), policies, [request],
                  [*principal_records, workspace_record])


def _classified_workspace(workspace_id: str | None, classification: WorkspaceDataClassification | None):
    resolved = classification is not None and classification.resolved
    level = classification.classification if resolved else None
    return level, workspace_entity(workspace_id, classification=level,
                                   classification_rank=classification.rank if resolved else None)


def model_query(admission: Any, alias: str | None, *, principal: Principal | None = None) -> PointQuery:
    normalized = str(alias or "").strip()
    verified = bool(admission.verified)
    level, (workspace, workspace_record) = _classified_workspace(admission.project_id,
                                                                 admission.data_classification)
    principal, principal_records = principal or getattr(admission, "principal", None) or _bound_principal()
    resource, resource_record = model_alias_entity(normalized, alias_approved_for(normalized))
    policies = platform_policies([FAMILY_MODEL])
    if level:
        policies += model_level_policies(level, admission.level_model_aliases.get(level))
    if verified:
        policies += workspace_model_policies(workspace.id, admission.policy)
    request = CedarRequest(principal, ACTION_CALL_MODEL, resource,
                           {"workspace": entity_value(workspace), "admission_verified": verified,
                            "route": ROUTE_GOVERNED, "content": dict(EMPTY_CONTENT)})
    return _query(POINT_MODEL_ADMISSION, ACTION_CALL_MODEL, workspace, principal, resource.label(), policies,
                  [request], [*principal_records, workspace_record, resource_record])


def remote_query(
    *, project_id: str, classification: WorkspaceDataClassification, data_policy_class: Any, model_kind: str,
    rules: LevelRules | None, principal: Principal | None = None,
) -> PointQuery:
    action = ACTION_USE_RERANKER if model_kind == REMOTE_KIND_RERANKER else ACTION_USE_REMOTE_EMBEDDINGS
    level, (workspace, workspace_record) = _classified_workspace(project_id, classification)
    alias_class = normalized_classification(data_policy_class)
    rank = classification_rank(alias_class) if alias_class in MODEL_DATA_POLICY_CLASSES else None
    resource, resource_record = remote_model_entity(model_kind, alias_class, rank)
    principal, principal_records = principal or _bound_principal()
    policies = platform_policies([FAMILY_REMOTE])
    if level and rules is not None:
        policies += remote_level_policies(level, reranker_allowed=rules.reranker_allowed,
                                          remote_embeddings_allowed=rules.remote_embeddings_allowed)
    request = CedarRequest(principal, action, resource, {"workspace": entity_value(workspace)})
    return _query(POINT_REMOTE_MODEL, action, workspace, principal, resource.label(), policies, [request],
                  [*principal_records, workspace_record, resource_record])


def tool_query(
    tool_name: str, section: Mapping[str, Any] | None, params: Mapping[str, Any] | None, *,
    principal: Principal | None = None, connections: Iterable[str] = (),
) -> PointQuery:
    from ..classification_tool_policy import tool_connector_family, tool_reads_logs, tool_writes

    name = str(tool_name or "").strip()
    section = section if isinstance(section, Mapping) else {}
    level = str(section["level"]) if section.get("level") else None
    workspace, workspace_record = workspace_entity(section.get("workspace_id") if level else None,
                                                   classification=level, classification_rank=classification_rank(level))
    family = tool_connector_family(name)
    writes = tool_writes(name, params)
    action = (ACTION_WRITE_CONNECTOR if writes else ACTION_READ_CONNECTOR) if family else ACTION_CALL_TOOL
    resource, resource_record = tool_entity(name, family)
    principal, principal_records = principal or _bound_principal()
    policies = platform_policies([FAMILY_TOOL])
    if level:
        policies += tool_level_policies(level, connectors=section.get("connectors") or {},
                                        log_masking_required=section.get("log_masking_required") is True)
    context = {"workspace": entity_value(workspace), "reads_logs": tool_reads_logs(name, params), "writes": writes,
               "connections": sorted({str(item) for item in connections})}
    request = CedarRequest(principal, action, resource, context)
    return _query(POINT_TOOL_ADMISSION, action, workspace, principal, resource.label(), policies, [request],
                  [*principal_records, workspace_record, resource_record])


__all__ = [
    "EMPTY_CONTENT",
    "POINTS",
    "POINT_DEVICE_DISPATCH",
    "POINT_GATEWAY_TOOL_CHECK",
    "POINT_MODEL_ADMISSION",
    "POINT_REMOTE_MODEL",
    "POINT_SEAT",
    "POINT_TOOL_ADMISSION",
    "POINT_TOOL_RESULT",
    "PointQuery",
    "alias_approved_for",
    "model_query",
    "remote_query",
    "seat_query",
    "tool_query",
]
