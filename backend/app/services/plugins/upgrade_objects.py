"""One object of an installed plugin moved to the new package (``upgrade.apply``)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import FlowDefinition, McpServerRegistration, Skill, User
from ...models.runtime.work_role_model import WorkRole, WorkRoleFunction
from ..mcp_audit_vocabulary import ACTION_CONFIGURATION_UPDATED
from .install import (
    _install_mcp,
    _install_skill,
    _install_workflow,
    _licence,
    _plugin_category,
    content_digest,
    publish_installed,
    skill_digest,
)
from .package import PluginPackage


async def _skill(db: AsyncSession, package: PluginPackage, skill, item: dict[str, Any], *, user: User,
                 findings: list[dict[str, Any]]) -> dict[str, Any]:
    from ..skill_catalog.bundle import BundleFile
    from ..skill_catalog.lifecycle import published_version
    from ..skill_catalog.spec import SKILL_FILE, render_skill_md
    from ..skill_catalog.versions import VersionContent, new_draft_row, write_content
    from ..skill_catalog.versions import content_digest as version_digest

    target = await db.get(Skill, item["id"])
    if target is None:  # removed from the catalog by an admin since: brought anew
        return await _install_skill(db, package, skill, user=user, findings=findings)
    digest = skill_digest(skill)
    if digest == item.get("digest") and not item.get("dropped"):
        return {**item, "digest": digest}
    manifest = package.manifest
    previous = await published_version(db, target)
    draft = await new_draft_row(db, target, actor_id=user.id, note=f"Plugin {manifest.id} {manifest.version}",
                                base_version=previous.version if previous is not None else None)
    db.add(draft)
    frontmatter = {**skill.frontmatter, "name": skill.name}
    files = [BundleFile(SKILL_FILE, render_skill_md(frontmatter, skill.body))]
    files += [BundleFile(path, text) for path, text in sorted(skill.files.items()) if path != SKILL_FILE]
    await write_content(db, target, draft, VersionContent(
        files=files, extension={}, available_platform_chat=True, available_octryx_claude=True,
        category_id=(previous.category_id if previous is not None else None) or await _plugin_category(db, user.id),
        licence_spdx=_licence(package)))
    draft.digest = version_digest(draft)
    await db.flush()
    await publish_installed(db, package, target, draft, user=user, findings=findings, previous=previous)
    return {"kind": "skill", "id": target.id, "key": skill.name, "created": True, "digest": digest}


async def _workflow(db: AsyncSession, package: PluginPackage, workflow, item: dict[str, Any], *, user: User,
                    workspace_id: str | None, install_id: str) -> dict[str, Any]:
    from ...models.runtime.flow_definition import FlowDefinitionVersion
    from ..flow_definitions import next_flow_version_number, publish_flow_definition_version, validate_flow_definition

    flow = await db.get(FlowDefinition, item["id"])
    if flow is None:
        return await _install_workflow(db, package, workflow, user=user, workspace_id=workspace_id,
                                       install_id=install_id)
    digest = content_digest(workflow.definition)
    flow.name, flow.description, flow.is_active = workflow.name, workflow.description, True
    if digest == item.get("digest"):
        return {**item, "digest": digest, "dropped": False}
    manifest = package.manifest
    version = FlowDefinitionVersion(
        flow_id=flow.id, version=await next_flow_version_number(db, flow_id=flow.id), status="draft",
        definition_json=workflow.definition, validation_report=validate_flow_definition(workflow.definition),
        publish_metadata={}, runtime_settings={}, policy_bindings={}, created_by=user.id)
    db.add(version)
    await db.flush()
    await publish_flow_definition_version(db, version_id=version.id, current_user=user, shipped=True,
                                          publish_metadata={"approval_mode": "plugin_install", "plugin": manifest.id,
                                                            "plugin_version": manifest.version,
                                                            "plugin_install_id": install_id})
    return {"kind": "workflow", "id": flow.id, "key": workflow.key, "created": True, "digest": digest}


async def _role(db: AsyncSession, role, mine: dict[tuple[str, str], dict[str, Any]], *, user: User,
                workspace_id: str | None) -> list[dict[str, Any]]:
    from ..work_role_model.admin_catalog import (
        create_function,
        create_role,
        set_function_tools,
        update_function,
        update_role,
    )

    made = []
    for function in role.functions:
        item = mine.get(("function", function["key"]))
        current = await db.get(WorkRoleFunction, item["id"]) if item else None
        if current is None:
            view = await create_function(db, user, {**function, "workspace_id": workspace_id})
            made.append({"kind": "function", "id": view["id"], "key": function["key"], "created": True})
            continue
        await update_function(db, user, current.id, {"name": function.get("name") or current.name,
                                                     "description": function.get("description") or "",
                                                     "expected_version": current.version})
        if list(current.tools_json or []) != list(function.get("tools") or []):
            await set_function_tools(db, user, current.id, {"tools": function.get("tools") or [],
                                                            "expected_tools_version": current.tools_version})
        made.append({"kind": "function", "id": current.id, "key": function["key"], "created": True})
    item = mine.get(("role", role.key))
    current = await db.get(WorkRole, item["id"]) if item else None
    body = {"name": role.name, "description": role.description, "function_keys": role.function_keys}
    if current is None:
        view = await create_role(db, user, {"key": role.key, "workspace_id": workspace_id, **body})
        made.append({"kind": "role", "id": view["id"], "key": role.key, "created": True})
    else:
        await update_role(db, user, current.id, {**body, "is_active": True, "expected_version": current.version})
        made.append({"kind": "role", "id": current.id, "key": role.key, "created": True})
    return made


async def _mcp(db: AsyncSession, server, item: dict[str, Any], *, user: User,
               workspace_id: str | None) -> dict[str, Any]:
    from ..mcp_server_registry import _audit_change
    from ..mcp_server_registry_config import validate_remote_url

    registration = await db.get(McpServerRegistration, item["id"])
    if registration is None:
        return await _install_mcp(db, server, user=user, workspace_id=workspace_id)
    changed = (registration.url, registration.transport, registration.description) != (
        server.url, server.transport, server.description)
    registration.is_active = True
    if changed:
        registration.url = validate_remote_url(server.url)
        registration.transport, registration.description = server.transport, server.description
        registration.updated_by, registration.revision = user.id, registration.revision + 1
        await db.refresh(registration, ["secret_bindings"])
        await _audit_change(db, registration=registration, actor_user_id=user.id, action=ACTION_CONFIGURATION_UPDATED)
        await _disconnect(registration.name)
    return {"kind": "mcp_server", "id": registration.id, "key": server.name, "created": True}


async def _disconnect(name: str) -> None:
    try:
        from ...plugins.mcp.client import mcp_client_manager

        await mcp_client_manager.disconnect(name)
    except Exception:  # noqa: BLE001 - not connected in this process (or no MCP runtime here): nothing to close
        pass


async def _drop(db: AsyncSession, item: dict[str, Any], *, user: User) -> dict[str, Any]:
    from ..skill_catalog.lifecycle import published_version, retire

    if item["kind"] == "skill":
        target = await db.get(Skill, item["id"])
        published = await published_version(db, target) if target is not None else None
        if published is not None:
            await retire(db, target, published, actor_id=user.id)
    model = {"workflow": FlowDefinition, "role": WorkRole, "mcp_server": McpServerRegistration}.get(item["kind"])
    target = await db.get(model, item["id"]) if model is not None else None
    if target is not None:
        target.is_active = False
    return {**item, "dropped": True}
