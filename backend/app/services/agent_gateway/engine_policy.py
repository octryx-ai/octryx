"""The effective coding engine for a person in a Workspace, and the three audited writes (``engine_keys``).

``effective_engine``: the person's own choice when the Workspace allows it, else the Workspace's default, else the
platform default, else the first allowed engine. Every write records an ``AuditLog`` row with before and after.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, Project, SystemConfig
from ...models.agent.agent_engine_choice import UserAgentEngine
from .engine_keys import (
    ENGINE_CLAUDE_CODE,
    ENGINES,
    ENGINES_KEY,
    PLATFORM_CONFIG_KEY,
    REASON_ENGINE_NOT_ALLOWED,
    EnginePolicyError,
    engine_name,
    normalize_engine_section,
)
from .policy_keys import AGENT_GATEWAY_POLICY_CONFIG_KEY, AgentGatewayPolicyError
from .policy_normalize import normalize_agent_gateway_policy

AUDIT_PLATFORM = "admin.agent_gateway.default_engine_updated"
AUDIT_WORKSPACE = "admin.agent_gateway.engines_updated"
AUDIT_PERSON = "user.agent_engine_updated"
REASON_POLICY_INVALID = "agent_gateway_policy_invalid"

SOURCE_PERSON = "person"
SOURCE_WORKSPACE = "workspace"
SOURCE_PLATFORM = "platform"


@dataclass(frozen=True, slots=True)
class EngineSetting:
    engine: str  # the effective engine
    source: str  # person | workspace | platform
    allowed: tuple[str, ...]
    workspace_default: str  # the default members get without a choice of their own
    platform_default: str
    person_choice: str | None  # the stored choice, even when the Workspace does not allow it

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "allowed": list(self.allowed)}


async def platform_default(db: AsyncSession) -> str:
    row = await db.get(SystemConfig, PLATFORM_CONFIG_KEY)
    value = str(row.value or "").strip() if row is not None else ""
    return value if value in ENGINES else ENGINE_CLAUDE_CODE


def workspace_section(config: Any) -> dict[str, Any] | None:
    """The Workspace's stored ``engines`` section, or ``None`` (none stored, or unreadable: the defaults apply)."""
    stored = config.get(AGENT_GATEWAY_POLICY_CONFIG_KEY) if isinstance(config, dict) else None
    section = stored.get(ENGINES_KEY) if isinstance(stored, dict) else None
    if section is None:
        return None
    try:
        return normalize_engine_section(section, ENGINES_KEY)
    except EnginePolicyError:
        return None


async def person_choice(db: AsyncSession, user_id: str) -> str | None:
    row = await db.get(UserAgentEngine, user_id)
    return row.engine if row is not None and row.engine in ENGINES else None


def resolve(*, platform: str, section: dict[str, Any] | None, choice: str | None) -> EngineSetting:
    allowed = tuple((section or {}).get("allowed") or ENGINES)
    workspace_default = (section or {}).get("default") or platform
    source_default = SOURCE_WORKSPACE if (section or {}).get("default") else SOURCE_PLATFORM
    if workspace_default not in allowed:
        workspace_default, source_default = allowed[0], SOURCE_WORKSPACE
    if choice in allowed:
        engine, source = choice, SOURCE_PERSON
    else:
        engine, source = workspace_default, source_default
    return EngineSetting(engine=engine, source=source, allowed=allowed, workspace_default=workspace_default,
                         platform_default=platform, person_choice=choice)


async def effective_engine(db: AsyncSession, *, user_id: str, workspace_id: str | None) -> EngineSetting:
    project = await db.get(Project, workspace_id) if workspace_id else None
    return resolve(platform=await platform_default(db),
                   section=workspace_section(project.config if project is not None else None),
                   choice=await person_choice(db, user_id))


async def set_platform_default(db: AsyncSession, *, engine: Any, actor_id: str) -> str:
    value = engine_name(engine, "default")
    row = await db.get(SystemConfig, PLATFORM_CONFIG_KEY)
    before = str(row.value or "") if row is not None else ""
    if row is None:
        row = SystemConfig(key=PLATFORM_CONFIG_KEY, description="Default coding engine of octryx sessions")
        db.add(row)
    row.value = value
    db.add(AuditLog(user_id=actor_id, action=AUDIT_PLATFORM, resource_type="system_config",
                    resource_id=PLATFORM_CONFIG_KEY, details={"before": before or ENGINE_CLAUDE_CODE, "after": value}))
    await db.flush()
    return value


async def set_workspace_engines(db: AsyncSession, *, project: Project, value: Any, actor_id: str) -> dict[str, Any]:
    """Store the validated section through the governed project-config path; raises ``EnginePolicyError``."""
    section = normalize_engine_section(value, f"{AGENT_GATEWAY_POLICY_CONFIG_KEY}.{ENGINES_KEY}")
    config = project.config if isinstance(project.config, dict) else {}
    stored = config.get(AGENT_GATEWAY_POLICY_CONFIG_KEY)
    if stored is not None:
        candidate = {**stored, ENGINES_KEY: section} if isinstance(stored, dict) else stored
        try:
            normalize_agent_gateway_policy(candidate)
        except AgentGatewayPolicyError as error:
            raise EnginePolicyError(REASON_POLICY_INVALID, error.path) from None
    before = stored.get(ENGINES_KEY) if isinstance(stored, dict) else None
    from ..admin.project.admin_project_config_service import apply_project_config_patch

    await apply_project_config_patch(
        db, project=project, patch={AGENT_GATEWAY_POLICY_CONFIG_KEY: {ENGINES_KEY: section}}, actor_user_id=actor_id)
    db.add(AuditLog(user_id=actor_id, action=AUDIT_WORKSPACE, resource_type="workspace", resource_id=project.id,
                    details={"before": before, "after": section}))
    await db.flush()
    return section


async def set_person_choice(db: AsyncSession, *, user_id: str, engine: Any, workspace_id: str | None = None) -> None:
    """Store (or with ``None`` clear) the person's own choice. With ``workspace_id`` the choice must be allowed
    there, so the setting the person sees is the one that applies; raises ``EnginePolicyError``."""
    row = await db.get(UserAgentEngine, user_id)
    before = row.engine if row is not None else None
    if engine is None:
        if row is not None:
            await db.delete(row)
    else:
        value = engine_name(engine, "engine")
        if workspace_id:
            setting = await effective_engine(db, user_id=user_id, workspace_id=workspace_id)
            if value not in setting.allowed:
                raise EnginePolicyError(REASON_ENGINE_NOT_ALLOWED, "engine")
        if row is None:
            db.add(UserAgentEngine(user_id=user_id, engine=value))
        else:
            row.engine = value
    db.add(AuditLog(user_id=user_id, action=AUDIT_PERSON, resource_type="user", resource_id=user_id,
                    details={"before": before, "after": engine, "workspace_id": workspace_id}))
    await db.flush()


__all__ = [
    "AUDIT_PERSON",
    "AUDIT_PLATFORM",
    "AUDIT_WORKSPACE",
    "EngineSetting",
    "effective_engine",
    "person_choice",
    "platform_default",
    "resolve",
    "set_person_choice",
    "set_platform_default",
    "set_workspace_engines",
    "workspace_section",
]
