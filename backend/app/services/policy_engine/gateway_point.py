"""The Cedar query of the gateway ``tool_rules`` check (``POINT_GATEWAY_TOOL_CHECK``).

One request per command segment and per candidate path. The decision log stores ``PointQuery.log_resource``: only
the tool name, the programs (argv[0]) and a hash of the arguments, never the command line or the paths (they can
carry secrets and personal data); the full ``resource`` stays in memory for the test bench.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from ..agent_gateway.policy import GatewayPolicy
from ..model_gateway.data_policy.classification import WorkspaceDataClassification
from .engine import CedarRequest, EntityRef, entity_value
from .entities import command_entity, path_entity
from .points import POINT_GATEWAY_TOOL_CHECK, PointQuery, _classified_workspace, _query
from .schema import ACTION_READ_PATH, ACTION_RUN_COMMAND, ACTION_WRITE_PATH, POINT_GATEWAY
from .translator import FAMILY_GATEWAY, platform_policies, workspace_gateway_policies

WRITE_PATH_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
MAX_LOG_RESOURCE_CHARS = 240


def arguments_digest(tool_input: Mapping[str, Any]) -> str:
    """A short, stable hash of a tool call's arguments: correlates records without storing the arguments."""
    canonical = json.dumps(tool_input, sort_keys=True, ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def gateway_query(
    *, workspace_id: str, gateway: GatewayPolicy, hook_input: Mapping[str, Any], principal: EntityRef,
    principal_records: Sequence[Mapping[str, Any]], classification: WorkspaceDataClassification | None = None,
) -> PointQuery:
    """The gateway ``tool_rules`` check: one request per command segment and per candidate path.

    ``classification``: the Workspace's resolved classification (``workspace_facts``), so policies can
    narrow coding agents by it; ``None`` or unresolved leaves the attributes absent (the conditions do not match).
    """
    from ..agent_gateway.command_match import command_segments
    from ..agent_gateway.tool_check import BASH_TOOL, PATH_FIELDS, candidate_paths

    tool_name = str(hook_input.get("tool_name") or "")
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    cwd = str(hook_input.get("cwd") or "")
    _level, (workspace, workspace_record) = _classified_workspace(workspace_id, classification)
    context = {"workspace": entity_value(workspace), "tool": tool_name, "point": POINT_GATEWAY}
    requests: list[CedarRequest] = []
    records: list[Mapping[str, Any]] = [*principal_records, workspace_record]
    labels: list[str] = []
    programs: list[str] = []
    if tool_name == BASH_TOOL:
        command = str(tool_input.get("command") or "")
        segments = command_segments(command)
        built = [command_entity("unparseable", None, command)] if segments is None else [
            command_entity(f"segment-{index}", segment) for index, segment in enumerate(segments)
        ]
        for ref, record in built:
            requests.append(CedarRequest(principal, ACTION_RUN_COMMAND, ref, context))
            records.append(record)
            labels.append(str(record["attrs"]["line"]))
            programs.append(str(record["attrs"]["program"]) or "unparseable")
    path_action = ACTION_WRITE_PATH if tool_name in WRITE_PATH_TOOLS else ACTION_READ_PATH
    for field in PATH_FIELDS:
        value = tool_input.get(field)
        if not isinstance(value, str):
            continue
        for path in candidate_paths(value, cwd):
            ref, record = path_entity(f"path-{len(requests)}", path)
            requests.append(CedarRequest(principal, path_action, ref, context))
            records.append(record)
            labels.append(path)
    action = ACTION_RUN_COMMAND if tool_name == BASH_TOOL else path_action
    policies = platform_policies([FAMILY_GATEWAY]) + workspace_gateway_policies(workspace.id, gateway).policies
    resource = f"{tool_name}: " + " | ".join(labels) if labels else tool_name
    log_resource = " ".join(part for part in (tool_name, " | ".join(dict.fromkeys(programs)),
                                              f"args {arguments_digest(tool_input)}") if part)
    return _query(POINT_GATEWAY_TOOL_CHECK, action, workspace, principal, resource, policies, requests, records,
                  log_resource=log_resource[:MAX_LOG_RESOURCE_CHARS])


__all__ = ["arguments_digest", "gateway_query"]
