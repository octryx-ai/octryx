"""Upgrade (and rollback) of an installed plugin: a different package of the same plugin in the same place.

plugins mostly come with the Octryx image (``image.py``), so image version = plugin version and a
rollback is an image rollback. Both are this one step: whatever package is installed, the objects of the install move
to it.

- An object both packages bring is updated in place and keeps its id: a skill gets a new published version (the
  previous one is retired), a workflow a new published version, a role and its functions their new name, description,
  tools and function list, an MCP server its new URL. Unchanged content (same digest) gets no new version.
- An object only the new package brings is created, as on install.
- An object only the old package brought is switched off and kept (``dropped``): its skill version retired, its
  workflow, role or MCP server inactive. Nothing is deleted; a later version that brings it again switches it back on.
- The UI bundle is replaced, the settings stay. A disabled install stays disabled.

Refused (``conflicts``): a name the new package brings that belongs to something else, an open draft of one of the
plugin's skills (an admin's edit is never overwritten), and an install of this plugin in another place that shares
its skills (skills are global; upgrade it there first or remove that install).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, Skill, User
from ...models.runtime.plugin_install import STATUS_ACTIVE, PluginInstall, PluginUiFile
from ...time_utils import utc_now
from .install import (
    _conflicts,
    _install_mcp,
    _install_skill,
    _install_workflow,
    skill_digest,
    skill_findings,
    store_ui_bundle,
    switch_contributions,
)
from .package import PluginPackage
from .upgrade_objects import _drop, _mcp, _role, _skill, _workflow

AUDIT_UPGRADED = "plugins.upgraded"


def _mine(row: PluginInstall) -> dict[tuple[str, str], dict[str, Any]]:
    return {(item["kind"], item["key"]): item for item in row.contributions_json or [] if item.get("created")}


async def conflicts(db: AsyncSession, row: PluginInstall, package: PluginPackage, *,
                    kinds: set[str] | None = None) -> list[dict[str, Any]]:
    """What stands in the way of moving ``row`` to ``package`` (empty = it can). ``kinds`` limits the check to those
    objects (the image moves its shared part and each Workspace's part separately, all in one start, so another
    install of the plugin is never in the way there)."""
    from ..skill_catalog.lifecycle import open_version

    mine, found = _mine(row), []
    elsewhere = (await db.execute(select(PluginInstall.scope, PluginInstall.workspace_id).where(
        PluginInstall.plugin_key == row.plugin_key, PluginInstall.id != row.id))).all()
    if elsewhere and package.skills and kinds is None:
        from ...models import Project

        ids = [workspace_id for _, workspace_id in elsewhere if workspace_id]
        names = dict((await db.execute(select(Project.id, Project.name).where(Project.id.in_(ids)))).all()) \
            if ids else {}
        places = [{"scope": scope, "workspace_id": workspace_id,
                   "name": names.get(workspace_id) if workspace_id else "Platform"}
                  for scope, workspace_id in elsewhere]
        found.append({"kind": "plugin", "key": row.plugin_key, "code": "plugin_installed_elsewhere",
                      "message": f"{row.name} is also installed in "
                                 f"{', '.join(str(place['name']) for place in places)} and shares its skills there "
                                 "(skills are global); upgrade or remove it there first.",
                      "places": places})
    # Names the new package brings that are not this install's: the install conflicts decide (a fresh install's view
    # with this install's own objects left out).
    fresh, _ = await _conflicts(db, package, "workspace" if row.workspace_id else "platform", row.workspace_id)
    for item in fresh:
        if item["code"] == "plugin_already_installed":
            continue
        if item["code"] == "plugin_version_differs":
            continue  # a skill this plugin brought elsewhere: covered by plugin_installed_elsewhere
        kind = "function" if item["kind"] == "function" else item["kind"]
        if (kind, item["key"]) in mine or (kinds is not None and kind not in kinds):
            continue
        found.append(item)
    for skill in package.skills if kinds is None or "skill" in kinds else []:
        item = mine.get(("skill", skill.name))
        target = await db.get(Skill, item["id"]) if item else None
        if target is not None and skill_digest(skill) != item.get("digest"):
            opened = await open_version(db, target)
            if opened is not None:
                found.append({"kind": "skill", "key": skill.name, "code": "skill_draft_open",
                              "message": f"'{skill.name}' has an open {opened.state} (version {opened.version}); "
                                         "publish or discard it first, the upgrade never overwrites it."})
    return found


def _brings(package: PluginPackage) -> list[tuple[str, str]]:
    keys = [("skill", skill.name) for skill in package.skills]
    for role in package.roles:
        keys += [("function", function["key"]) for function in role.functions] + [("role", role.key)]
    keys += [("workflow", workflow.key) for workflow in package.workflows]
    return keys + [("mcp_server", server.name) for server in package.manifest.mcp_servers]


def changes(row: PluginInstall, package: PluginPackage) -> dict[str, list[dict[str, str]]]:
    """What the upgrade adds, keeps (updated where its content changed) and switches off, as ``{kind, key}``."""
    mine = {key for key, item in _mine(row).items() if not item.get("dropped")}
    new = _brings(package)

    def listed(keys) -> list[dict[str, str]]:
        return [{"kind": kind, "key": key} for kind, key in keys]

    return {"added": listed(key for key in new if key not in mine),
            "kept": listed(key for key in new if key in mine),
            "dropped": listed(sorted(mine - set(new)))}


async def apply(db: AsyncSession, row: PluginInstall, package: PluginPackage, *, user: User, source: dict[str, Any],
                consent: str, granted: dict[str, Any], findings: dict[str, list[dict[str, Any]]],
                kinds: set[str] | None = None, refs: list[dict[str, Any]] | None = None) -> PluginInstall:
    """Move ``row`` to ``package`` (the caller checked ``conflicts`` and the consent); flushes, the caller commits.

    ``kinds`` moves only those objects (``skill``, ``mcp_server``, ``workflow``, ``role`` with its functions, ``ui``);
    the others stay as they are. ``refs`` replaces the objects the install shares with another one (``created:
    False``): a Workspace's activation of an image plugin refers to the image's skills and MCP servers."""
    manifest, mine = package.manifest, _mine(row)

    def moves(kind: str) -> bool:
        return kinds is None or kind in kinds

    workspace_id, previous = row.workspace_id, {"version": row.version, "package_digest": row.package_digest,
                                                 "source": row.source_json}
    all_findings = skill_findings(package)
    made: list[dict[str, Any]] = []
    for skill in package.skills if moves("skill") else []:
        item = mine.get(("skill", skill.name))
        made.append(await _skill(db, package, skill, item, user=user, findings=all_findings[skill.name]) if item
                    else await _install_skill(db, package, skill, user=user, findings=all_findings[skill.name]))
    for role in package.roles if moves("role") else []:
        made += await _role(db, role, mine, user=user, workspace_id=workspace_id)
    for workflow in package.workflows if moves("workflow") else []:
        item = mine.get(("workflow", workflow.key))
        made.append(await _workflow(db, package, workflow, item, user=user, workspace_id=workspace_id,
                                         install_id=row.id) if item
                    else await _install_workflow(db, package, workflow, user=user, workspace_id=workspace_id,
                                                 install_id=row.id))
    for server in manifest.mcp_servers if moves("mcp_server") else []:
        item = mine.get(("mcp_server", server.name))
        made.append(await _mcp(db, server, item, user=user, workspace_id=workspace_id) if item
                    else await _install_mcp(db, server, user=user, workspace_id=workspace_id))
    kept = {(item["kind"], item["key"]) for item in made}
    for key, item in mine.items():
        if key in kept:
            continue
        if not moves("role" if item["kind"] == "function" else item["kind"]):
            made.append(item)  # not moved here
        else:
            made.append(item if item.get("dropped") else await _drop(db, item, user=user))
    shared = [item for item in row.contributions_json or [] if not item.get("created")]
    made = (list(refs) if refs is not None else shared) + made
    if moves("ui"):
        await db.execute(delete(PluginUiFile).where(PluginUiFile.install_id == row.id))
        store_ui_bundle(db, row, package)
    row.name, row.version, row.publisher, row.description = (manifest.name, manifest.version, manifest.publisher,
                                                             manifest.description)
    row.source_json, row.package_digest, row.consent_digest = source, package.digest, consent
    row.manifest_json, row.permissions_json, row.contributions_json = manifest.as_dict(), granted, made
    row.findings_json = [{"skill": name, **entry} for name, entries in findings.items() for entry in entries]
    row.updated_by, row.updated_at = user.id, utc_now()
    await switch_contributions(db, row, row.status == STATUS_ACTIVE, actor_id=user.id)
    db.add(AuditLog(user_id=user.id, action=AUDIT_UPGRADED, resource_type="plugin_install", resource_id=row.id,
                    details={"plugin": manifest.id, "from_version": previous["version"], "version": manifest.version,
                             "scope": row.scope, "workspace_id": workspace_id, "package_digest": package.digest,
                             "previous_package_digest": previous["package_digest"], "consent_digest": consent,
                             "source": source, "previous_source": previous["source"], "contributions": made}))
    await db.flush()
    return row


__all__ = ["AUDIT_UPGRADED", "apply", "changes", "conflicts"]
