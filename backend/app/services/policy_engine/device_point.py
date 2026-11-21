"""The ``device_dispatch`` enforcement point's Cedar query: may this user run a chat request of the
Workspace on this device with this profile?

Built from the facts the device dispatch gate already holds (``devices/device_policy``): the Workspace's
classification, its ``device_runs`` section, the matrix rule of its level, the device and whether the folder is in
its reported allowlist.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.services.data_classification.policy_rules import LevelRules

from ..model_gateway.data_policy.classification import WorkspaceDataClassification
from .device_translator import device_level_policies, workspace_device_policies
from .engine import CedarRequest, entity_value
from .entities import device_entity
from .points import POINT_DEVICE_DISPATCH, PointQuery, Principal, _bound_principal, _classified_workspace, _query
from .schema import ACTION_RUN_ON_DEVICE
from .translator import FAMILY_DEVICE, platform_policies


def device_query(
    *, workspace_id: str, classification: WorkspaceDataClassification | None, rules: LevelRules | None,
    raw_policy: Mapping[str, Any] | None, device: Any, profile: str, folder_allowlisted: bool,
    principal: Principal | None = None,
) -> PointQuery:
    level, (workspace, workspace_record) = _classified_workspace(workspace_id, classification)
    resource, resource_record = device_entity(device.id, owner_user_id=device.owner_user_id, os=device.os,
                                              profiles=device.profiles or [], status=device.status)
    principal, principal_records = principal or _bound_principal()
    policies = platform_policies([FAMILY_DEVICE])
    if level and rules is not None:
        policies += device_level_policies(level, device_runs_allowed=rules.device_runs_allowed)
    policies += workspace_device_policies(workspace.id, raw_policy)
    request = CedarRequest(principal, ACTION_RUN_ON_DEVICE, resource, {
        "workspace": entity_value(workspace), "profile": profile, "folder_allowlisted": bool(folder_allowlisted)})
    return _query(POINT_DEVICE_DISPATCH, ACTION_RUN_ON_DEVICE, workspace, principal, resource.label(), policies,
                  [request], [*principal_records, workspace_record, resource_record])


__all__ = ["device_query"]
