"""Preview and install of a plugin package: the installer sees what it wants, confirms, and is responsible."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, FlowDefinition, McpServerRegistration, Skill, User
from ...models.runtime.plugin_install import (
    PLATFORM_SCOPE_KEY,
    SCOPE_PLATFORM,
    STATUS_ACTIVE,
    STATUS_DISABLED,
    PluginInstall,
)
from ...models.runtime.work_role_model import WorkRole, WorkRoleFunction
from ...time_utils import utc_now
from ..skill_catalog.scanner import scan
from .package import PluginPackage

AUDIT_INSTALLED, AUDIT_DISABLED, AUDIT_ENABLED = "plugins.installed", "plugins.disabled", "plugins.enabled"
APPROVAL_MODE = "plugin_install"
LICENCE_DEFAULT = "Internal"
PLUGIN_CATEGORY = "plugins"


class PluginError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, **details: Any) -> None:
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.details}


def scope_key(scope: str, workspace_id: str | None) -> str:
    return PLATFORM_SCOPE_KEY if scope == SCOPE_PLATFORM else str(workspace_id)


def _licence(package: PluginPackage) -> str:
    return package.manifest.license or LICENCE_DEFAULT


def skill_findings(package: PluginPackage) -> dict[str, list[dict[str, Any]]]:
    licence = _licence(package)
    return {skill.name: scan("skill", {"SKILL.md": skill.text, **skill.files}, executable=set(),
                             scripts_allowed=False, licence=licence, launch_spec=None)
            for skill in package.skills}


async def _contributed_by(db: AsyncSession, kind: str, object_id: str) -> list[PluginInstall]:
    rows = (await db.execute(select(PluginInstall))).scalars().all()
    return [row for row in rows if any(item.get("kind") == kind and item.get("id") == object_id
                                       for item in row.contributions_json or [])]


async def _conflicts(db: AsyncSession, package: PluginPackage, scope: str, workspace_id: str | None
                     ) -> tuple[list[dict[str, Any]], dict[str, str]]:
    manifest, conflicts, shared = package.manifest, [], {}
    existing = (await db.execute(select(PluginInstall).where(
        PluginInstall.plugin_key == manifest.id,
        PluginInstall.scope_key == scope_key(scope, workspace_id)))).scalar_one_or_none()
    if existing is not None:
        conflicts.append({"kind": "plugin", "key": manifest.id, "code": "plugin_already_installed",
                          "message": f"{manifest.name} {existing.version} is already installed here."})
    for skill in package.skills:
        found = (await db.execute(select(Skill).where(Skill.name == skill.name))).scalar_one_or_none()
        if found is None:
            continue
        # Shared = brought by this plugin's install in *another* scope (this scope's own install is a conflict).
        owners = [row for row in await _contributed_by(db, "skill", found.id)
                  if row.plugin_key == manifest.id and row.scope_key != scope_key(scope, workspace_id)]
        if not owners:
            conflicts.append({"kind": "skill", "key": skill.name, "code": "skill_name_taken",
                              "message": f"A skill named '{skill.name}' exists and does not come from this plugin."})
        elif any(row.version != manifest.version for row in owners):
            conflicts.append({"kind": "skill", "key": skill.name, "code": "plugin_version_differs",
                              "message": f"'{skill.name}' is installed elsewhere from version "
                                         f"{owners[0].version}; install that version or upgrade it everywhere."})
        else:
            shared[skill.name] = found.id
    for workflow in package.workflows:
        clause = (FlowDefinition.project_id == workspace_id) if workspace_id else FlowDefinition.project_id.is_(None)
        if (await db.execute(select(FlowDefinition.id).where(FlowDefinition.key == workflow.key, clause))).first():
            conflicts.append({"kind": "workflow", "key": workflow.key, "code": "workflow_key_taken",
                              "message": f"A workflow with key '{workflow.key}' exists here."})
    scope_value = workspace_id or "global"
    for role in package.roles:
        if (await db.execute(select(WorkRole.id).where(WorkRole.key == role.key,
                                                       WorkRole.scope_key == scope_value))).first():
            conflicts.append({"kind": "role", "key": role.key, "code": "role_key_taken",
                              "message": f"A role with key '{role.key}' exists here."})
        brought = {function["key"] for function in role.functions}
        known = set((await db.execute(select(WorkRoleFunction.key).where(
            WorkRoleFunction.scope_key.in_({scope_value, "global"})))).scalars())
        missing = sorted(set(role.function_keys) - brought - known)
        if missing:
            conflicts.append({"kind": "role", "key": role.key, "code": "role_function_unknown",
                              "message": f"Role '{role.key}' needs functions this Octryx does not have: "
                                         f"{', '.join(missing)}."})
        for function in role.functions:
            if (await db.execute(select(WorkRoleFunction.id).where(WorkRoleFunction.key == function["key"],
                                                                   WorkRoleFunction.scope_key == scope_value))).first():
                conflicts.append({"kind": "function", "key": function["key"], "code": "function_key_taken",
                                  "message": f"A function with key '{function['key']}' exists here."})
    for server in package.manifest.mcp_servers:
        if (await db.execute(select(McpServerRegistration.id).where(
                McpServerRegistration.name == server.name))).first():
            conflicts.append({"kind": "mcp_server", "key": server.name, "code": "mcp_server_name_taken",
                              "message": f"An MCP server named '{server.name}' exists."})
    return conflicts, shared


def permissions(package: PluginPackage) -> dict[str, Any]:
    manifest = package.manifest
    return {
        "connections": manifest.connections, "egress": manifest.egress, "writes": manifest.writes,
        "skills": [{"name": s.name, "description": str(s.frontmatter.get("description") or "")}
                   for s in package.skills],
        "workflows": [{"key": w.key, "name": w.name, "writes": w.writes} for w in package.workflows],
        "roles": [{"key": r.key, "name": r.name, "function_keys": r.function_keys} for r in package.roles],
        "functions": [f for r in package.roles for f in r.functions],
        "mcp_servers": [{"name": s.name, "url": s.url, "transport": s.transport, "tools": s.tools}
                        for s in manifest.mcp_servers],
        # Recorded now, active later: the UI slots and a container Octryx starts.
        "server": manifest.server, "ui": manifest.ui,
        "settings": package.settings_schema,
    }


def consent_digest(package: PluginPackage, scope: str, workspace_id: str | None, granted: dict[str, Any],
                   upgrade_from: str | None = None) -> str:
    payload = {"package": package.digest, "scope": scope, "workspace_id": workspace_id, "permissions": granted}
    if upgrade_from:
        payload["upgrade_from"] = upgrade_from  # an upgrade is confirmed as one: from this version to the package's
    return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


async def installed_here(db: AsyncSession, plugin_key: str, scope: str, workspace_id: str | None
                         ) -> PluginInstall | None:
    return (await db.execute(select(PluginInstall).where(
        PluginInstall.plugin_key == plugin_key,
        PluginInstall.scope_key == scope_key(scope, workspace_id)))).scalar_one_or_none()


async def _plugin_category(db: AsyncSession, actor_id: str) -> str:
    from ...models import SkillCategory
    from ..skill_catalog.categories import create_category

    found = (await db.execute(select(SkillCategory.id).where(SkillCategory.key == PLUGIN_CATEGORY))).scalar()
    if found:
        return found
    category = await create_category(db, {"key": PLUGIN_CATEGORY, "label": "Plugins",
                                          "description": "Skills that installed plugins brought."}, actor_id=actor_id)
    return category.id


def store_ui_bundle(db: AsyncSession, row: PluginInstall, package: PluginPackage) -> int:
    import mimetypes

    from ...models.runtime.plugin_install import PluginUiFile

    bundle = ((package.manifest.ui or {}).get("bundle") or "").strip("/")
    if not bundle:
        return 0
    prefix, count = bundle + "/", 0
    for path, data in sorted(package.files.items()):
        if path.startswith(prefix):
            relative = path[len(prefix):]
            kind = mimetypes.guess_type(relative)[0] or "application/octet-stream"
            db.add(PluginUiFile(install_id=row.id, path=relative, content_type=kind, size=len(data),
                                sha256=hashlib.sha256(data).hexdigest(), content=data))
            count += 1
    return count


def content_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def skill_digest(skill) -> str:
    return content_digest({"SKILL.md": skill.text, **skill.files})


async def publish_installed(db: AsyncSession, package: PluginPackage, created: Skill, row, *, user: User,
                            findings: list[dict[str, Any]], previous=None) -> None:
    from ...models import Approval
    from ..skill_catalog.adoption import approval_action
    from ..skill_catalog.lifecycle import AUDIT_PUBLISHED, AUDIT_RETIRED, _audit, publish_checks
    from ..skill_catalog.versions import sync_identity

    manifest = package.manifest
    # The installer saw these findings and confirmed: the acknowledgement the catalog's review would record.
    row.acknowledged_findings = [item["id"] for item in findings if item.get("acknowledge")]
    await publish_checks(db, created, row)
    now = utc_now()
    approval = Approval(requested_by=user.id, approved_by=user.id, workspace_id=None, status="approved",
                        action=approval_action(row), resolved_at=now,
                        reason=f"Installed with plugin {manifest.id} {manifest.version} (installer confirmed)")
    db.add(approval)
    await db.flush()
    if previous is not None:
        previous.state, previous.retired_by, previous.retired_at, previous.updated_at = "retired", user.id, now, now
        _audit(db, user.id, AUDIT_RETIRED, created, previous, replaced_by=row.version, plugin=manifest.id)
        await db.flush()
    row.state, row.approval_id, row.published_by, row.published_at = "published", approval.id, user.id, now
    row.submitted_by, row.submitted_at, row.updated_at = user.id, now, now
    await db.flush()
    await sync_identity(db, created, row)
    _audit(db, user.id, AUDIT_PUBLISHED, created, row, approval_mode=APPROVAL_MODE, plugin=manifest.id,
           plugin_version=manifest.version,
           previous_version=previous.version if previous is not None else None)
    await db.flush()


async def _install_skill(db: AsyncSession, package: PluginPackage, skill, *, user: User,
                         findings: list[dict[str, Any]]) -> dict[str, Any]:
    from ..skill_catalog.lifecycle import create_skill

    manifest = package.manifest
    created, row = await create_skill(db, {"category_id": await _plugin_category(db, user.id),
        "name": skill.name, "frontmatter": skill.frontmatter, "body": skill.body, "files": skill.files,
        "licence_spdx": _licence(package), "note": f"Plugin {manifest.id} {manifest.version}",
        "tags": ["plugin"], "available_platform_chat": True, "available_octryx_claude": True,
    }, actor_id=user.id)
    await publish_installed(db, package, created, row, user=user, findings=findings)
    return {"kind": "skill", "id": created.id, "key": skill.name, "created": True, "digest": skill_digest(skill)}


async def _install_workflow(db: AsyncSession, package: PluginPackage, workflow, *, user: User,
                            workspace_id: str | None, install_id: str) -> dict[str, Any]:
    from ..flow_definitions import create_flow_definition, publish_flow_definition_version

    manifest = package.manifest
    flow = await create_flow_definition(db, current_user=user, payload={
        "key": workflow.key, "name": workflow.name, "description": workflow.description,
        "project_id": workspace_id, "definition": workflow.definition, "is_active": True,
    })
    # shipped: the install is the approval (the installer is responsible), recorded on the version.
    await publish_flow_definition_version(db, version_id=flow["current_version_id"], current_user=user, shipped=True,
                                          publish_metadata={"approval_mode": APPROVAL_MODE, "plugin": manifest.id,
                                                            "plugin_version": manifest.version,
                                                            "plugin_install_id": install_id})
    return {"kind": "workflow", "id": flow["id"], "key": workflow.key, "created": True,
            "digest": content_digest(workflow.definition)}


async def _install_role(db: AsyncSession, role, *, user: User, workspace_id: str | None) -> list[dict[str, Any]]:
    from ..work_role_model.admin_catalog import create_function, create_role

    made = []
    for function in role.functions:
        view = await create_function(db, user, {**function, "workspace_id": workspace_id})
        made.append({"kind": "function", "id": view["id"], "key": function["key"], "created": True})
    view = await create_role(db, user, {"key": role.key, "name": role.name, "description": role.description,
                                        "workspace_id": workspace_id, "function_keys": role.function_keys})
    made.append({"kind": "role", "id": view["id"], "key": role.key, "created": True})
    return made


async def _install_mcp(db: AsyncSession, server, *, user: User, workspace_id: str | None) -> dict[str, Any]:
    from ..mcp_server_registry_writes import create_remote_mcp_server
    from ..mcp_workspace_allow import set_workspace_server

    registration = await create_remote_mcp_server(db, body={
        "owner_scope": "workspace" if workspace_id else "platform", "workspace_id": workspace_id,
        "name": server.name, "transport": server.transport, "url": server.url,
        "description": server.description, "is_active": True,
    }, actor_user_id=user.id, commit=False)
    if workspace_id:
        await set_workspace_server(db, workspace_id=workspace_id, server_id=registration.id, allowed=True,
                                   actor_id=user.id)
    return {"kind": "mcp_server", "id": registration.id, "key": server.name, "created": True}


async def switch_contributions(db: AsyncSession, row: PluginInstall, active: bool, *,
                               actor_id: str | None = None) -> None:
    from ..mcp_workspace_allow import set_workspace_server

    for item in row.contributions_json or []:
        if item["kind"] == "mcp_server" and row.workspace_id and actor_id and not item.get("created"):
            if await db.get(McpServerRegistration, item["id"]) is not None:
                await set_workspace_server(db, workspace_id=row.workspace_id, server_id=item["id"],
                                           allowed=active and not item.get("dropped"), actor_id=actor_id)
        if not item.get("created"):
            continue
        model = {"workflow": FlowDefinition, "role": WorkRole, "mcp_server": McpServerRegistration}.get(item["kind"])
        target = await db.get(model, item["id"]) if model is not None else None
        if target is not None:
            target.is_active = active and not item.get("dropped")


async def set_status(db: AsyncSession, row: PluginInstall, *, status: str, user: User,
                     reason: str | None = None) -> PluginInstall:
    if status not in (STATUS_ACTIVE, STATUS_DISABLED):
        raise PluginError("plugin_status_invalid", "status is 'active' or 'disabled'.", 422)
    if row.status == status:
        return row
    active = status == STATUS_ACTIVE
    await switch_contributions(db, row, active, actor_id=user.id)
    row.status, row.updated_by, row.updated_at = status, user.id, utc_now()
    db.add(AuditLog(user_id=user.id, action=AUDIT_ENABLED if active else AUDIT_DISABLED,
                    resource_type="plugin_install", resource_id=row.id,
                    project_id=row.workspace_id,
                    details={"plugin": row.plugin_key, "version": row.version, "scope": row.scope,
                             "workspace_id": row.workspace_id, **({"reason": reason} if reason else {})}))
    await db.flush()
    return row


async def install_views(db: AsyncSession, rows: list[PluginInstall]) -> list[dict[str, Any]]:
    ids = {value for row in rows for value in (row.installed_by, row.updated_by) if value}
    users = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all() if ids else []
    names = {user.id: user.display_name or user.username for user in users}
    return [install_view(row, names) for row in rows]


def install_view(row: PluginInstall, names: dict[str, str] | None = None) -> dict[str, Any]:
    manifest, names = dict(row.manifest_json or {}), names or {}
    return {
        "id": row.id, "plugin": row.plugin_key, "name": row.name, "version": row.version,
        "publisher": row.publisher, "description": row.description, "scope": row.scope,
        "workspace_id": row.workspace_id, "status": row.status, "source": row.source_json,
        "package_digest": row.package_digest, "consent_digest": row.consent_digest,
        "permissions": row.permissions_json, "contributions": row.contributions_json, "findings": row.findings_json,
        "ui": (manifest.get("contributes") or {}).get("ui"),
        "installed_by": row.installed_by, "installed_by_name": names.get(row.installed_by or ""),
        "installed_at": row.installed_at.isoformat() if row.installed_at else None,
        "updated_by": row.updated_by, "updated_by_name": names.get(row.updated_by or ""),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def to_http(error: PluginError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=error.detail())


__all__ = ["AUDIT_DISABLED", "AUDIT_ENABLED", "AUDIT_INSTALLED", "PluginError", "consent_digest", "content_digest",
           "install_view", "install_views", "installed_here", "permissions", "publish_installed",
           "scope_key", "set_status", "skill_digest", "switch_contributions", "to_http"]
