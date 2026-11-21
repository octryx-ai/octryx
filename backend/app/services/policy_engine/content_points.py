"""Cedar queries of the content points: a model request or a tool result with what the scan found.

- :func:`model_content_query` — ``call_model`` with ``context.route`` and ``context.content``:
  on the **governed** route the same baseline fragment as the content-free admission (``points.model_query``:
  the model family, the level's alias list, the Workspace's grants) plus the content family; on the **seat** route
  the content family alone (its ``platform:seat-route-permit`` grants what the seat route's own checks admitted),
  with the resource ``ModelAlias::"seat:<model>"`` that is approved for nothing.
- :func:`tool_result_query` — ``receive_tool_result`` (baseline: ``platform:tool-result-permit``).

The principal's ``sensitive`` set is the conversation's categories (``entities.with_sensitive``). The decision
log stores the resource label only (an alias, a tool name): never content.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .engine import CedarRequest, EntityRef, entity_value
from .entities import model_alias_entity, tool_entity, with_sensitive
from .points import (
    POINT_MODEL_ADMISSION,
    POINT_TOOL_RESULT,
    PointQuery,
    Principal,
    _bound_principal,
    _classified_workspace,
    _query,
)
from .schema import (
    ACTION_CALL_MODEL,
    ACTION_RECEIVE_TOOL_RESULT,
    ROUTE_GOVERNED,
    ROUTE_SEAT,
    SEAT_MODEL_PREFIX,
)
from .translator import (
    FAMILY_CONTENT,
    FAMILY_MODEL,
    SECRETS_POLICY_ID,
    model_level_policies,
    platform_policies,
    workspace_model_policies,
)


def _principal(principal: Principal | None, sensitive: Iterable[str]) -> tuple[EntityRef, list[Mapping[str, Any]]]:
    ref, records = principal or _bound_principal()
    return ref, with_sensitive(ref, records, sensitive)


def model_content_query(
    *, route: str, alias: str, content: Mapping[str, Any], approved_for: Iterable[str] = (),
    admission: Any = None, workspace_id: str | None = None, classification: Any = None,
    principal: Principal | None = None, sensitive: Iterable[str] = (), secret_policy: bool = True,
) -> PointQuery:
    """``admission``: the governed route's ``ProjectModelAdmission`` (it carries the Workspace and its sources).

    ``secret_policy``: include ``platform:secrets-never-leave`` — only where the gateway's secret scan is the
    existing check (the inbound routes), so the shadow comparison stays equal on the platform's chat driver.
    """
    if route not in (ROUTE_GOVERNED, ROUTE_SEAT) or (route == ROUTE_GOVERNED and admission is None):
        raise ValueError("content_route_invalid")  # a governed question needs its admission; no silent seat
    if route == ROUTE_GOVERNED:
        level, (workspace, workspace_record) = _classified_workspace(admission.project_id,
                                                                     admission.data_classification)
        verified = bool(admission.verified)
        policies = platform_policies([FAMILY_MODEL, FAMILY_CONTENT])
        if level:
            policies += model_level_policies(level, admission.level_model_aliases.get(level))
        if verified:
            policies += workspace_model_policies(workspace.id, admission.policy)
        principal = principal or getattr(admission, "principal", None)
        resource, resource_record = model_alias_entity(alias, approved_for)
    else:
        _level, (workspace, workspace_record) = _classified_workspace(workspace_id, classification)
        verified = True
        policies = platform_policies([FAMILY_CONTENT])
        resource, resource_record = model_alias_entity(f"{SEAT_MODEL_PREFIX}{alias}")
    if not secret_policy:
        policies = [item for item in policies if item.policy_id != SECRETS_POLICY_ID]
    ref, records = _principal(principal, sensitive)
    context = {"workspace": entity_value(workspace), "admission_verified": verified, "route": route,
               "content": dict(content)}
    request = CedarRequest(ref, ACTION_CALL_MODEL, resource, context)
    return _query(POINT_MODEL_ADMISSION, ACTION_CALL_MODEL, workspace, ref, f"{route} {resource.label()}", policies,
                  [request], [*records, workspace_record, resource_record])


def tool_result_query(
    *, tool_name: str, family: str | None, origin: str, content: Mapping[str, Any], workspace_id: str | None,
    classification: Any = None, connections: Iterable[str] = (), principal: Principal | None = None,
    sensitive: Iterable[str] = (),
) -> PointQuery:
    _level, (workspace, workspace_record) = _classified_workspace(workspace_id, classification)
    resource, resource_record = tool_entity(tool_name, family)
    ref, records = _principal(principal, sensitive)
    context = {"workspace": entity_value(workspace), "origin": origin, "content": dict(content),
               "connections": sorted({str(item) for item in connections})}
    request = CedarRequest(ref, ACTION_RECEIVE_TOOL_RESULT, resource, context)
    return _query(POINT_TOOL_RESULT, ACTION_RECEIVE_TOOL_RESULT, workspace, ref, f"{origin} {resource.label()}",
                  platform_policies([FAMILY_CONTENT]), [request], [*records, workspace_record, resource_record])


__all__ = ["model_content_query", "tool_result_query"]
