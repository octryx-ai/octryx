"""Plugins from the image: a folder Octryx reads at every start."""

from __future__ import annotations

import logging
import os
import secrets
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, Role, User, UserRole
from ...models.runtime.plugin_install import (
    SCOPE_PLATFORM,
    SCOPE_WORKSPACE,
    STATUS_ACTIVE,
    STATUS_DISABLED,
    PluginInstall,
)
from ...time_utils import utc_now
from .install import (
    AUDIT_INSTALLED,
    PluginError,
    _conflicts,
    _install_mcp,
    _install_role,
    _install_skill,
    _install_workflow,
    installed_here,
    permissions,
    scope_key,
    set_status,
    skill_findings,
    store_ui_bundle,
    switch_contributions,
)
from .package import PackageError, PluginPackage, files_from_folder, files_from_zip, read_package

logger = logging.getLogger(__name__)

PLUGIN_DIR_ENV = "OCTRYX_PLUGIN_DIR"
DEFAULT_PLUGIN_DIR = "/opt/octryx/plugins"
SOURCE_KIND = "image"
SERVICE_USERNAME = "octryx-image-plugins"
ACCOUNT_TYPE = "plugin_service"
MISSING_REASON = "missing_from_image"
_LOCK_ID = 0x0C7_9106  # pg advisory lock: one replica syncs at a time
SHARED_KINDS = {"skill", "mcp_server"}  # the image's install holds them, once
WORKSPACE_KINDS = {"workflow", "role", "function", "ui"}  # each Workspace's activation has its own
AUDIT_ACTIVATED = "plugins.activated"


@dataclass
class SyncReport:
    folder: str
    started_at: str = ""
    folder_exists: bool = False
    entries: list[dict[str, Any]] = field(default_factory=list)

    def add(self, entry: str, outcome: str, **details: Any) -> None:
        self.entries.append({"entry": entry, "outcome": outcome, **details})

    def as_dict(self) -> dict[str, Any]:
        return {"folder": self.folder, "folder_exists": self.folder_exists, "started_at": self.started_at,
                "entries": self.entries}


LAST_REPORT: SyncReport | None = None


def plugin_dir() -> Path:
    return Path(os.environ.get(PLUGIN_DIR_ENV) or DEFAULT_PLUGIN_DIR)


def read_folder(folder: Path, report: SyncReport) -> dict[str, tuple[str, PluginPackage]]:
    found: dict[str, tuple[str, PluginPackage]] = {}
    duplicates: set[str] = set()
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        if path.name.startswith("."):
            continue
        try:
            if path.is_dir():
                files = files_from_folder(path)
            elif path.suffix.lower() == ".zip" and path.is_file():
                files = files_from_zip(path.read_bytes())
            else:
                continue
            package = read_package(files)
        except PackageError as error:
            report.add(path.name, "failed", code="plugin_package_invalid", issues=error.issues)
            continue
        key = package.manifest.id
        if key in found:
            duplicates.add(key)
            report.add(path.name, "failed", plugin=key, code="plugin_duplicate_in_image",
                       message=f"{key} is in the folder more than once ({found[key][0]}, {path.name}).")
            continue
        found[key] = (path.name, package)
    for key in duplicates:  # which one is meant is unclear: neither is installed
        entry, _ = found.pop(key)
        report.add(entry, "failed", plugin=key, code="plugin_duplicate_in_image",
                   message=f"{key} is in the folder more than once.")
    return found


async def service_user(db: AsyncSession) -> User:
    from ..auth import hash_password

    user = (await db.execute(select(User).where(User.username == SERVICE_USERNAME))).scalar_one_or_none()
    if user is not None and user.account_type != ACCOUNT_TYPE:
        raise RuntimeError(f"username '{SERVICE_USERNAME}' belongs to another account")
    if user is None:
        user = User(id=str(uuid.uuid4()), username=SERVICE_USERNAME,
                    email=f"{SERVICE_USERNAME}@plugins.octryx.invalid",
                    password_hash=hash_password(secrets.token_urlsafe(48)), auth_source=ACCOUNT_TYPE,
                    account_type=ACCOUNT_TYPE, display_name="Octryx image (plugins)", is_active=False)
        db.add(user)
        await db.flush()
    admin = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one_or_none()
    if admin is None:
        raise RuntimeError("The 'admin' role is not seeded")
    held = (await db.execute(select(UserRole.role_id).where(UserRole.user_id == user.id))).scalars().all()
    if admin.id not in held:
        db.add(UserRole(user_id=user.id, role_id=admin.id))
        await db.flush()
    return user


async def _lock(db: AsyncSession) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": _LOCK_ID})


def _source(entry: str, package: PluginPackage, folder: Path) -> dict[str, Any]:
    return {"kind": SOURCE_KIND, "entry": entry, "folder": str(folder), "package_digest": package.digest}


def is_image_part(row: PluginInstall) -> bool:
    return row.scope == SCOPE_PLATFORM and (row.source_json or {}).get("kind") == SOURCE_KIND


def refs(part: PluginInstall) -> list[dict[str, Any]]:
    return [{"kind": item["kind"], "id": item["id"], "key": item["key"], "created": False}
            for item in part.contributions_json or [] if item["kind"] in SHARED_KINDS and not item.get("dropped")]


def _refused(found: list[dict[str, Any]]) -> PluginError:
    return PluginError("plugin_not_installable", "; ".join(str(item.get("message") or item["code"])
                                                             for item in found)[:500], conflicts=found)


async def _image_part(db: AsyncSession, package: PluginPackage, source: dict[str, Any], user: User) -> PluginInstall:
    manifest = package.manifest
    found = [item for item in (await _conflicts(db, package, SCOPE_PLATFORM, None))[0]
             if item["kind"] in SHARED_KINDS | {"plugin"}]
    if found:
        raise _refused(found)
    row = PluginInstall(
        plugin_key=manifest.id, name=manifest.name, version=manifest.version, publisher=manifest.publisher,
        description=manifest.description, scope=SCOPE_PLATFORM, scope_key=scope_key(SCOPE_PLATFORM, None),
        workspace_id=None, status=STATUS_ACTIVE, source_json=source, package_digest=package.digest,
        consent_digest=package.digest, manifest_json=manifest.as_dict(), permissions_json=permissions(package),
        contributions_json=[], findings_json=[], installed_by=user.id, updated_by=user.id)
    db.add(row)
    await db.flush()
    findings = skill_findings(package)
    made = [await _install_skill(db, package, skill, user=user, findings=findings[skill.name])
            for skill in package.skills]
    made += [await _install_mcp(db, server, user=user, workspace_id=None) for server in manifest.mcp_servers]
    row.contributions_json = made
    row.findings_json = [{"skill": name, **item} for name, items in findings.items() for item in items]
    db.add(AuditLog(user_id=user.id, action=AUDIT_INSTALLED, resource_type="plugin_install", resource_id=row.id,
                    project_id=row.workspace_id,
                    details={"plugin": manifest.id, "version": manifest.version, "scope": SCOPE_PLATFORM,
                             "package_digest": package.digest, "source": source, "contributions": made}))
    await db.flush()
    return row


async def _move(db: AsyncSession, row: PluginInstall, package: PluginPackage, source: dict[str, Any], user: User,
                kinds: set[str], shared: list[dict[str, Any]] | None = None) -> None:
    from . import upgrade

    found = await upgrade.conflicts(db, row, package, kinds=kinds)
    if found:
        raise _refused(found)
    findings = {name: items for name, items in skill_findings(package).items() if items}
    await upgrade.apply(db, row, package, user=user, source={**source, **_kept(row)}, consent=package.digest,
                        granted=permissions(package), findings=findings, kinds=kinds, refs=shared)


def _kept(row: PluginInstall) -> dict[str, Any]:
    return {MISSING_REASON: True} if (row.source_json or {}).get(MISSING_REASON) else {}


async def _activations(db: AsyncSession, plugin_key: str) -> list[PluginInstall]:
    rows = (await db.execute(select(PluginInstall).where(PluginInstall.plugin_key == plugin_key,
                                                         PluginInstall.scope == SCOPE_WORKSPACE))).scalars().all()
    return [row for row in rows if (row.source_json or {}).get("kind") == SOURCE_KIND]


async def _switch_on(db: AsyncSession, rows: list[PluginInstall], user: User) -> bool:
    back = False
    for row in rows:
        source = dict(row.source_json or {})
        if source.pop(MISSING_REASON, None):
            row.source_json = source
            await set_status(db, row, status=STATUS_ACTIVE, user=user, reason="back_in_image")
            back = True
    return back


async def sync_one(db: AsyncSession, entry: str, package: PluginPackage, folder: Path, user: User,
                   report: SyncReport) -> None:
    manifest = package.manifest
    row = await installed_here(db, manifest.id, SCOPE_PLATFORM, None)
    source = _source(entry, package, folder)
    activations = await _activations(db, manifest.id)
    details = {"plugin": manifest.id, "version": manifest.version, "workspaces": len(activations)}
    if row is None:
        await _image_part(db, package, source, user)
        report.add(entry, "available", **details)
        return
    if row.package_digest == package.digest:
        back = await _switch_on(db, [row, *activations], user)
        report.add(entry, "enabled" if back else "unchanged", **details)
        return
    previous = row.version
    await _move(db, row, package, source, user, SHARED_KINDS)
    for activation in activations:
        await _move(db, activation, package, source, user, WORKSPACE_KINDS, shared=refs(row))
    await _switch_on(db, [row, *activations], user)
    report.add(entry, "upgraded", from_version=previous, **details)


async def switch_off_missing(db: AsyncSession, present: set[str], user: User, report: SyncReport) -> None:
    rows = (await db.execute(select(PluginInstall))).scalars().all()
    for row in rows:
        source = dict(row.source_json or {})
        if source.get("kind") != SOURCE_KIND or row.plugin_key in present or source.get(MISSING_REASON):
            continue
        if row.status != STATUS_ACTIVE:
            continue  # switched off by an admin: stays off, also when the plugin is back
        row.source_json = {**source, MISSING_REASON: True}
        await set_status(db, row, status=STATUS_DISABLED, user=user, reason=MISSING_REASON)
        if is_image_part(row):
            report.add(source.get("entry") or row.plugin_key, "disabled", plugin=row.plugin_key, version=row.version,
                       code=MISSING_REASON)


# ---- a Workspace admin activates an image plugin -----------------------------------------------------------------

async def activate(db: AsyncSession, plugin_key: str, workspace_id: str, user: User) -> PluginInstall:
    part = await installed_here(db, plugin_key, SCOPE_PLATFORM, None)
    if part is None or not is_image_part(part) or part.status != STATUS_ACTIVE:
        raise PluginError("plugin_not_available", "This plugin is not in the Octryx image.", 404)
    row = await installed_here(db, plugin_key, SCOPE_WORKSPACE, workspace_id)
    if row is not None:
        if row.status != STATUS_ACTIVE:
            await set_status(db, row, status=STATUS_ACTIVE, user=user, reason="activated")
        return row
    package = _package(part)
    manifest = package.manifest
    found = [item for item in (await _conflicts(db, package, SCOPE_WORKSPACE, workspace_id))[0]
             if item["kind"] in {"workflow", "role", "function"}]
    if found:
        raise _refused(found)
    row = PluginInstall(
        plugin_key=manifest.id, name=manifest.name, version=manifest.version, publisher=manifest.publisher,
        description=manifest.description, scope=SCOPE_WORKSPACE, scope_key=scope_key(SCOPE_WORKSPACE, workspace_id),
        workspace_id=workspace_id, status=STATUS_ACTIVE, source_json=dict(part.source_json or {}),
        package_digest=package.digest, consent_digest=package.digest, manifest_json=manifest.as_dict(),
        permissions_json=permissions(package), contributions_json=[], findings_json=list(part.findings_json or []),
        installed_by=user.id, updated_by=user.id)
    db.add(row)
    await db.flush()
    store_ui_bundle(db, row, package)
    made = refs(part)
    for role in package.roles:
        made += await _install_role(db, role, user=user, workspace_id=workspace_id)
    for workflow in package.workflows:
        made.append(await _install_workflow(db, package, workflow, user=user, workspace_id=workspace_id,
                                            install_id=row.id))
    row.contributions_json = made
    await switch_contributions(db, row, True, actor_id=user.id)
    db.add(AuditLog(user_id=user.id, action=AUDIT_ACTIVATED, resource_type="plugin_install", resource_id=row.id,
                    project_id=row.workspace_id,
                    details={"plugin": manifest.id, "version": manifest.version, "workspace_id": workspace_id,
                             "package_digest": package.digest, "contributions": made}))
    await db.flush()
    return row


def _package(part: PluginInstall) -> PluginPackage:
    source = part.source_json or {}
    path = Path(str(source.get("folder") or plugin_dir())) / str(source.get("entry") or "")
    try:
        files = files_from_folder(path) if path.is_dir() else files_from_zip(path.read_bytes())
        package = read_package(files)
    except (OSError, PackageError):
        raise PluginError("plugin_not_available", "The plugin is no longer in the image's folder.", 404) from None
    if package.digest != part.package_digest:
        raise PluginError("plugin_not_available", "The image's folder changed since the start; restart Octryx.", 409)
    return package


async def available(db: AsyncSession, workspace_id: str | None) -> list[dict[str, Any]]:
    from .summary import needs_settings, summary

    parts = [row for row in (await db.execute(select(PluginInstall).where(
        PluginInstall.scope == SCOPE_PLATFORM).order_by(PluginInstall.name))).scalars().all() if is_image_part(row)]
    here = {}
    if workspace_id:
        here = {row.plugin_key: row for row in (await db.execute(select(PluginInstall).where(
            PluginInstall.workspace_id == workspace_id))).scalars().all()}
    active: dict[str, int] = {}
    for row in (await db.execute(select(PluginInstall).where(PluginInstall.scope == SCOPE_WORKSPACE,
                                                             PluginInstall.status == STATUS_ACTIVE))).scalars():
        if (row.source_json or {}).get("kind") == SOURCE_KIND:
            active[row.plugin_key] = active.get(row.plugin_key, 0) + 1
    views = []
    for part in parts:
        row = here.get(part.plugin_key)
        views.append({
            "plugin": part.plugin_key, "name": part.name, "version": part.version, "publisher": part.publisher,
            "description": part.description, "in_image": part.status == STATUS_ACTIVE,
            "active_workspaces": active.get(part.plugin_key, 0),  # live: Workspaces where it is on now
            "summary": summary(part.manifest_json or {}),
            "active": bool(row is not None and row.status == STATUS_ACTIVE),
            "install_id": row.id if row is not None else None,
            "needs_settings": needs_settings(_schema(part), row),
        })
    return views


def _schema(part: PluginInstall) -> dict[str, Any] | None:
    schema = (part.permissions_json or {}).get("settings")
    return schema if isinstance(schema, dict) else None


def failure(error: Exception) -> tuple[str, str, dict[str, Any]]:
    if isinstance(error, PluginError):
        return error.code, error.message, {k: v for k, v in error.details.items() if k in ("conflicts",
                                                                                          "blocking_findings")}
    detail = getattr(error, "detail", None)
    if isinstance(detail, dict):
        message = str(detail.get("message") or "")
        if not message and isinstance(detail.get("errors"), list):  # a workflow validation report
            message = "; ".join(str(item.get("message") or item) for item in detail["errors"][:5]
                                if isinstance(item, dict))
        return str(detail.get("code") or "plugin_install_failed"), message[:500] or "The install was refused.", {}
    as_detail = getattr(error, "as_detail", None)
    if callable(as_detail):  # skill catalog errors
        found = as_detail()
        return str(found.get("code") or "plugin_install_failed"), str(found.get("message") or found.get("code")), {}
    code = getattr(error, "code", None)
    if isinstance(code, str):  # role model errors
        return code, str(getattr(error, "message", "") or error)[:500], {}
    if detail:
        return "plugin_install_failed", str(detail)[:500], {}
    return "plugin_install_failed", "Unexpected error; see the server log.", {}


async def sync_image_plugins(session_factory, folder: Path | None = None) -> SyncReport:
    global LAST_REPORT
    folder = folder or plugin_dir()
    report = SyncReport(folder=str(folder), started_at=utc_now().isoformat(), folder_exists=folder.is_dir())
    if not report.folder_exists:
        # No folder is not an empty folder: nothing is installed and nothing switched off (a missing mount must
        # never disable the platform's plugins).
        LAST_REPORT = report
        return report
    packages = read_folder(folder, report)
    async with session_factory() as db:
        await _lock(db)
        rows = (await db.execute(select(PluginInstall.id).where(PluginInstall.scope_key == "platform"))).first()
        if not packages and rows is None:
            await db.rollback()
            LAST_REPORT = report
            return report  # no folder, no image plugins: nothing to do (the usual case)
        user = await service_user(db)
        await db.commit()
        user_id = user.id
    for key, (entry, package) in packages.items():
        async with session_factory() as db:
            try:
                await _lock(db)
                await sync_one(db, entry, package, folder, await db.get(User, user_id), report)
                await db.commit()
            except Exception as error:  # noqa: BLE001 - one plugin never stops the start
                await db.rollback()
                code, message, details = failure(error)
                report.add(entry, "failed", plugin=key, version=package.manifest.version, code=code,
                           message=message, **details)
                logger.warning("Image plugin %s not brought in: %s (%s)", key, message, type(error).__name__)
    async with session_factory() as db:
        try:
            await _lock(db)
            await switch_off_missing(db, set(packages), await db.get(User, user_id), report)
            await db.commit()
        except Exception as error:  # noqa: BLE001
            await db.rollback()
            logger.warning("Image plugins: switching off missing ones failed: %s", error)
    for item in report.entries:
        level = logging.WARNING if item["outcome"] == "failed" else logging.INFO
        logger.log(level, "Image plugin %s: %s", item.get("plugin") or item["entry"], item["outcome"],
                   extra={"plugin_entry": item})
    LAST_REPORT = report
    return report


__all__ = ["AUDIT_ACTIVATED", "DEFAULT_PLUGIN_DIR", "LAST_REPORT", "PLUGIN_DIR_ENV", "SOURCE_KIND", "SyncReport",
           "activate", "available", "is_image_part", "plugin_dir", "read_folder", "service_user",
           "sync_image_plugins", "sync_one", "switch_off_missing"]
