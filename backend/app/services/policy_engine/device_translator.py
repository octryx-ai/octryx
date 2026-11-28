"""The generated ``run_on_device`` policies: platform, classification matrix and Workspace ``device_runs``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..devices.device_runs_keys import device_runs_section
from .cedar_text import GeneratedPolicy, entity, literal, policy, string_set
from .schema import ACTION_RUN_ON_DEVICE, ENTITY_WORKSPACE

FORBID = "forbid"
PERMIT = "permit"


def _level(level: str) -> str:
    return f"context.workspace has classification && context.workspace.classification == {literal(level)}"


def device_platform_policies() -> list[GeneratedPolicy]:
    return [
        policy("platform:device-run-permit", PERMIT, actions=[ACTION_RUN_ON_DEVICE]),
        policy("platform:device-run-folder-not-allowlisted", FORBID, actions=[ACTION_RUN_ON_DEVICE],
               unless=["context.folder_allowlisted"]),
    ]


def device_level_policies(level: str, *, device_runs_allowed: bool) -> list[GeneratedPolicy]:
    if device_runs_allowed:
        return []
    return [policy(f"classification:{level}:device-runs-not-allowed", FORBID, actions=[ACTION_RUN_ON_DEVICE],
                   when=[_level(level)])]


def workspace_device_policies(workspace_id: str, raw_policy: Mapping[str, Any] | None) -> list[GeneratedPolicy]:
    scope = f"context.workspace == {entity(ENTITY_WORKSPACE, workspace_id)}"
    prefix = f"workspace:{workspace_id}"
    section = device_runs_section(dict(raw_policy) if raw_policy is not None else None)
    if raw_policy is None or section["enabled"] is not True:
        return [policy(f"{prefix}:device-runs-disabled", FORBID, actions=[ACTION_RUN_ON_DEVICE], when=[scope])]
    profiles = sorted(section["allowed_profiles"])
    return [policy(f"{prefix}:device-profile-not-allowed", FORBID, actions=[ACTION_RUN_ON_DEVICE],
                   when=[scope, f"!{string_set(profiles)}.contains(context.profile)"])]


__all__ = ["device_level_policies", "device_platform_policies", "workspace_device_policies"]
