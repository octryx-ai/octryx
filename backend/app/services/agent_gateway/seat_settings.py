"""The Workspace's stored seat settings (``agent_gateway_policy`` seat keys): how they read, and their writes."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, Project
from .policy_keys import AGENT_GATEWAY_POLICY_CONFIG_KEY, AgentGatewayPolicyError
from .policy_normalize import normalize_agent_gateway_policy
from .seat_policy_keys import (
    BASELINE_SEAT_MODELS,
    CODEX_SEAT_MODE_KEY,
    CODEX_SEAT_MODELS_KEY,
    REQUIRES_GOVERNED_KEY,
    SEAT_ALLOWS_GOVERNED_MODELS_KEY,
    SEAT_MODE_ALLOWED,
    SEAT_MODE_FORBIDDEN,
    SEAT_MODE_KEY,
    SEAT_MODELS_KEY,
    SeatPolicyError,
    normalize_seat_policy,
)

SEAT_MODE_AUDIT_ACTION = "admin.agent_gateway.seat_mode_updated"


def stored_seat_mode(config: object, key: str = SEAT_MODE_KEY) -> str:
    policy = config.get(AGENT_GATEWAY_POLICY_CONFIG_KEY) if isinstance(config, dict) else None
    value = policy.get(key) if isinstance(policy, dict) else None
    return SEAT_MODE_ALLOWED if value == SEAT_MODE_ALLOWED else SEAT_MODE_FORBIDDEN


def seat_mode_set(config: object, key: str = SEAT_MODE_KEY) -> bool:
    policy = config.get(AGENT_GATEWAY_POLICY_CONFIG_KEY) if isinstance(config, dict) else None
    return isinstance(policy, dict) and key in policy


REASON_POLICY_INVALID_FOR_WRITE = "agent_gateway_policy_invalid"


def _require_mergeable_policy(project: Project, seat_mode: object, key: str = SEAT_MODE_KEY) -> None:
    config = project.config if isinstance(project.config, dict) else {}
    stored = config.get(AGENT_GATEWAY_POLICY_CONFIG_KEY)
    if stored is None:
        return
    candidate = {**stored, key: seat_mode} if isinstance(stored, dict) else stored
    try:
        normalize_agent_gateway_policy(candidate)
    except AgentGatewayPolicyError as error:
        raise SeatPolicyError(REASON_POLICY_INVALID_FOR_WRITE, error.path) from None


SEAT_SWITCH_KEYS = (SEAT_MODE_KEY, CODEX_SEAT_MODE_KEY)
# The seat keys the settings card writes, one per call (the seat-mode route); every other policy key stays as stored.
SEAT_SETTING_KEYS = (*SEAT_SWITCH_KEYS, REQUIRES_GOVERNED_KEY, SEAT_MODELS_KEY, SEAT_ALLOWS_GOVERNED_MODELS_KEY,
                     CODEX_SEAT_MODELS_KEY)


def stored_seat_setting(config: object, key: str) -> Any:
    if key in SEAT_SWITCH_KEYS:
        return stored_seat_mode(config, key)
    policy = config.get(AGENT_GATEWAY_POLICY_CONFIG_KEY) if isinstance(config, dict) else None
    value = policy.get(key) if isinstance(policy, dict) else None
    if key == SEAT_MODELS_KEY:
        return list(value) if isinstance(value, list) and value else list(BASELINE_SEAT_MODELS)
    if key == CODEX_SEAT_MODELS_KEY:
        # ``None``: no list stored, every Codex model.
        return list(value) if isinstance(value, list) and value else None
    return value is True


def invalid_seat_settings(config: object) -> list[str]:
    policy = config.get(AGENT_GATEWAY_POLICY_CONFIG_KEY) if isinstance(config, dict) else None
    if not isinstance(policy, dict):
        return []
    invalid = []
    for key in SEAT_SETTING_KEYS:
        if key in policy:
            try:
                normalize_seat_policy({key: policy[key]}, AGENT_GATEWAY_POLICY_CONFIG_KEY)
            except SeatPolicyError:
                invalid.append(key)
    return invalid


async def set_workspace_seat_setting(
    db: AsyncSession, *, project: Project, key: str, value: object, actor_id: str, platform_admin: bool
) -> Any:
    if key not in SEAT_SETTING_KEYS:
        raise ValueError(key)
    path = AGENT_GATEWAY_POLICY_CONFIG_KEY
    if key in SEAT_SWITCH_KEYS and not isinstance(value, str):
        raise SeatPolicyError("invalid_seat_mode", f"{path}.{key}")
    # ``codex_seat_models: null`` drops the list again: every Codex model (the key's absent default).
    clearing = key == CODEX_SEAT_MODELS_KEY and value is None
    normalized = None if clearing else normalize_seat_policy({key: value}, path)[key]
    if not clearing:
        _require_mergeable_policy(project, normalized, key)
    before = stored_seat_setting(project.config, key)
    # A Workspace admin or owner may only tighten.
    if not platform_admin:
        from ..workspace_settings.bounds import check_seat_setting

        check_seat_setting(key, before, normalized)
    from ..admin.project.admin_project_config_service import apply_project_config_patch

    if clearing:
        config = project.config if isinstance(project.config, dict) else {}
        stored = config.get(AGENT_GATEWAY_POLICY_CONFIG_KEY)
        remaining = {k: v for k, v in stored.items() if k != key} if isinstance(stored, dict) else {}
        await apply_project_config_patch(
            db, project=project, patch={AGENT_GATEWAY_POLICY_CONFIG_KEY: remaining}, actor_user_id=actor_id,
            replace_keys=frozenset({AGENT_GATEWAY_POLICY_CONFIG_KEY}),
        )
    else:
        await apply_project_config_patch(
            db, project=project, patch={AGENT_GATEWAY_POLICY_CONFIG_KEY: {key: normalized}},
            actor_user_id=actor_id,
        )
    db.add(
        AuditLog(
            user_id=actor_id,
            action=SEAT_MODE_AUDIT_ACTION,
            resource_type="workspace",
            resource_id=project.id,
            details={key: normalized, "before": {key: before}, "after": {key: normalized}},
        )
    )
    await db.flush()
    return normalized


async def set_workspace_seat_mode(
    db: AsyncSession, *, project: Project, seat_mode: object, actor_id: str, platform_admin: bool,
    key: str = SEAT_MODE_KEY,
) -> str:
    if key not in SEAT_SWITCH_KEYS:
        raise ValueError(key)
    return str(await set_workspace_seat_setting(db, project=project, key=key, value=seat_mode, actor_id=actor_id,
                                                platform_admin=platform_admin))


__all__ = [
    "SEAT_MODE_AUDIT_ACTION",
    "SEAT_SETTING_KEYS",
    "SEAT_SWITCH_KEYS",
    "invalid_seat_settings",
    "seat_mode_set",
    "set_workspace_seat_mode",
    "set_workspace_seat_setting",
    "stored_seat_mode",
    "stored_seat_setting",
]
