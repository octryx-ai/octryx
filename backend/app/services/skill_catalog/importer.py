"""Import into the catalog: upload, Git repository and marketplace entry. Every import is a draft.

**Inspect** reads a repository once, read-only, at one commit: every skill folder (name, description, spec
issues, file and script counts, licence), every MCP server of a plugin, and what is ignored. **Import** takes the
commit the inspect showed (never re-resolves the ref) and the selected items, and creates one draft per item with
full provenance: source, path, commit, upstream bundle digest and an upstream snapshot (the later 3-way merge
base). The nearest LICENSE text (skill folder, then each parent folder up to the repository root) is bundled as
``LICENSE``, because MIT and MPL-2.0 require the notice to travel with the copy.

An item that already exists from the same source and path is an **update**: it goes through the upstream update
(3-way merge, local edits kept), never through a plain re-import. A name taken by another skill is refused.
"""

from __future__ import annotations

import json
import posixpath
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, Skill, SkillCategory, SkillSource, SkillUpstreamSnapshot, SkillVersion
from ...models.agent.skill_catalog import (
    SKILL_KIND_MCP_SERVER,
    SKILL_KIND_SKILL,
    TRACKING_FOLLOW,
    TRACKING_MODES,
    TRACKING_PINNED,
)
from ...time_utils import utc_now
from .archive import read_upload
from .bundle import BundleError, BundleFile, bundle_digest, classify, decode_text, manifest, store_blobs
from .errors import SkillCatalogError
from .git_source import (
    COMMIT_PATTERN,
    MODE_EXECUTABLE,
    RepoSnapshot,
    git_fetcher,
    normalize_repo_path,
    normalize_repository_url,
)
from .layout import MARKETPLACE_FILE, FoundPlugin, FoundSkill, find_layout, resolve_marketplace_entry
from .licence import LICENCE_FILE_NAMES, detect_licence
from .mcp_entry import MCP_FILE, PLUGIN_MANIFEST, launch_spec, servers_in_plugin
from .scanner import scan, summary
from .settings import CatalogSettings, load_settings
from .sources import git_source, source_token, upload_source
from .spec import SKILL_FILE, SkillSpecError, name_issue, parse_skill_md, stripped_keys, validate_skill
from .versions import UpstreamRef, VersionContent, new_draft_row, set_upstream, write_content

AUDIT_IMPORTED = "skill_catalog.imported"
MAX_IMPORT_ITEMS = 50


@dataclass(frozen=True, slots=True)
class GitTarget:
    url: str
    ref: str
    path: str
    named_connection_id: str | None
    marketplace_plugin: str | None


@dataclass(slots=True)
class OpenedTarget:
    snapshot: RepoSnapshot
    url: str
    ref: str
    base_path: str
    plugin: dict[str, Any] | None


def git_target(payload: dict[str, Any], settings: CatalogSettings) -> GitTarget:
    return GitTarget(
        url=normalize_repository_url(payload.get("url"), settings.allowed_hosts),
        ref=str(payload.get("ref") or "HEAD").strip()[:200] or "HEAD",
        path=normalize_repo_path(payload.get("path") or ""),
        named_connection_id=str(payload.get("named_connection_id") or "") or None,
        marketplace_plugin=str(payload.get("marketplace_plugin") or "").strip() or None,
    )


@asynccontextmanager
async def open_target(db: AsyncSession, target: GitTarget, settings: CatalogSettings,
                      commit: str | None = None) -> AsyncIterator[OpenedTarget]:
    """The repository at ``commit`` (or the ref's current commit); a marketplace entry is followed to its plugin."""
    token = await source_token(db, target.named_connection_id)
    fetcher = git_fetcher()
    pinned = commit if commit and COMMIT_PATTERN.match(commit) else None
    async with AsyncExitStack() as stack:
        resolved = pinned or await fetcher.resolve(target.url, target.ref, token=token)
        snapshot = await stack.enter_async_context(fetcher.open(target.url, resolved, token=token))
        if target.marketplace_plugin is None:
            yield OpenedTarget(snapshot, target.url, target.ref, target.path, None)
            return
        if MARKETPLACE_FILE not in snapshot.entries:
            raise SkillCatalogError("marketplace_not_found", 422, message="No .claude-plugin/marketplace.json.")
        text = decode_text(MARKETPLACE_FILE, (await snapshot.read_many([MARKETPLACE_FILE]))[MARKETPLACE_FILE])
        plugin = resolve_marketplace_entry(text, target.marketplace_plugin, set(snapshot.entries))
        described = {"name": plugin.name, **{key: plugin.entry.get(key) for key in (
            "description", "category", "version", "license", "homepage") if plugin.entry.get(key) is not None},
            "author": (plugin.entry.get("author") or {}).get("name") if isinstance(plugin.entry.get("author"), dict)
            else plugin.entry.get("author"), "marketplace": target.url, "marketplace_commit": resolved}
        if plugin.url is None:
            yield OpenedTarget(snapshot, target.url, target.ref, plugin.path, described)
            return
        external_url = normalize_repository_url(plugin.url, settings.allowed_hosts)
        external_ref = plugin.ref or "HEAD"
        external_commit = await fetcher.resolve(external_url, external_ref, token=None)
        external = await stack.enter_async_context(fetcher.open(external_url, external_commit, token=None))
        yield OpenedTarget(external, external_url, external_ref, plugin.path, described)


def _join(root: str, name: str) -> str:
    return f"{root}/{name}" if root else name


def _ancestors(path: str) -> list[str]:
    chain, current = [], path
    while True:
        chain.append(current)
        if not current:
            return chain
        current = posixpath.dirname(current)


def _licence_candidates(snapshot: RepoSnapshot, folder: str) -> list[str]:
    for root in _ancestors(folder):
        for name in LICENCE_FILE_NAMES:
            path = _join(root, name)
            if path in snapshot.entries:
                return [path]
    return []


def _plugin_manifest_path(snapshot: RepoSnapshot, folder: str) -> str | None:
    return next((_join(root, PLUGIN_MANIFEST) for root in _ancestors(folder)
                 if _join(root, PLUGIN_MANIFEST) in snapshot.entries), None)


async def _texts(snapshot: RepoSnapshot, paths: list[str]) -> dict[str, str]:
    raw = await snapshot.read_many(sorted(set(paths)))
    try:
        return {path: decode_text(path, data) for path, data in raw.items()}
    except BundleError as error:
        raise SkillCatalogError(error.code, 422, message=error.message, **error.details) from None


def _plugin_licence(texts: dict[str, str], manifest_path: str | None, plugin: dict[str, Any] | None) -> Any:
    if plugin and plugin.get("license"):
        return plugin["license"]
    if manifest_path and manifest_path in texts:
        try:
            document = json.loads(texts[manifest_path])
        except ValueError:
            return None
        return document.get("license") if isinstance(document, dict) else None
    return None


async def _existing(db: AsyncSession, name: str, url: str, path: str) -> dict[str, Any] | None:
    skill = (await db.execute(select(Skill).where(Skill.name == name))).scalar_one_or_none()
    if skill is None:
        return None
    source = await db.get(SkillSource, skill.source_id) if skill.source_id else None
    same = source is not None and source.url == url and skill.upstream_path == path
    return {"skill_id": skill.id, "relation": "update" if same else "name_taken", "kind": skill.kind}


async def inspect_git(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    settings = await load_settings(db)
    target = git_target(payload, settings)
    async with open_target(db, target, settings) as opened:
        snapshot = opened.snapshot
        layout = find_layout(snapshot.paths(), opened.base_path)
        if opened.base_path and not any(path == opened.base_path or path.startswith(f"{opened.base_path}/")
                                        for path in snapshot.entries):
            raise SkillCatalogError("skill_source_path_missing", 422, path=opened.base_path)
        wanted = [_join(item.path, SKILL_FILE) for item in layout.skills]
        for item in [*layout.skills, *layout.plugins]:
            wanted += _licence_candidates(snapshot, item.path)
            manifest_path = _plugin_manifest_path(snapshot, item.path)
            wanted += [manifest_path] if manifest_path else []
        wanted += [_join(plugin.path, name) for plugin in layout.plugins for name in plugin.files]
        texts = await _texts(snapshot, wanted)
        skills = [await _inspect_skill(db, opened, snapshot, item, texts, settings) for item in layout.skills]
        servers = [entry for plugin in layout.plugins
                   for entry in await _inspect_plugin(db, opened, snapshot, plugin, texts, settings)]
        repo_licence = detect_licence(frontmatter_licence=None, plugin_licence=None, repository_files={
            path: texts[path] for path in _licence_candidates(snapshot, "") if path in texts})
        return {
            "url": opened.url, "ref": opened.ref, "commit": snapshot.commit, "path": opened.base_path,
            "requested": {"url": target.url, "ref": target.ref, "path": target.path,
                          "marketplace_plugin": target.marketplace_plugin},
            "plugin": opened.plugin, "licence": {"spdx": repo_licence.spdx, "source": repo_licence.source},
            "skills": skills, "mcp_servers": servers, "ignored": layout.ignored,
        }


async def _inspect_skill(db: AsyncSession, opened: OpenedTarget, snapshot: RepoSnapshot, item: FoundSkill,
                         texts: dict[str, str], settings: CatalogSettings) -> dict[str, Any]:
    text = texts.get(_join(item.path, SKILL_FILE), "")
    try:
        parsed = parse_skill_md(text)
        frontmatter = parsed.frontmatter
        issues = [issue.as_dict() for issue in validate_skill(
            parsed.frontmatter, parsed.body, folder_name=item.name, skill_md_text=text, paths=list(item.files))]
    except SkillSpecError as error:
        frontmatter = {}
        issues = [{"code": error.code, "severity": "error", "field": "frontmatter", "message": error.message}]
    licence = detect_licence(
        frontmatter_licence=frontmatter.get("license"),
        plugin_licence=_plugin_licence(texts, _plugin_manifest_path(snapshot, item.path), opened.plugin),
        repository_files={path: texts[path] for path in _licence_candidates(snapshot, item.path) if path in texts})
    scripts = [path for path in item.files
               if classify(path, "", snapshot.entries[_join(item.path, path)].mode == MODE_EXECUTABLE) == "script"]
    return {
        "kind": SKILL_KIND_SKILL, "path": item.path, "name": item.name,
        "description": str(frontmatter.get("description") or ""), "files": len(item.files),
        "scripts": scripts, "execution_keys": stripped_keys(frontmatter), "spec_issues": issues,
        "importable": not any(issue["severity"] == "error" for issue in issues),
        "licence": {"spdx": licence.spdx, "source": licence.source, "allowed": settings.licence_allowed(licence.spdx)},
        "existing": await _existing(db, item.name, opened.url, item.path),
    }


async def _inspect_plugin(db: AsyncSession, opened: OpenedTarget, snapshot: RepoSnapshot, plugin: FoundPlugin,
                          texts: dict[str, str], settings: CatalogSettings) -> list[dict[str, Any]]:
    files = {name: texts[_join(plugin.path, name)] for name in plugin.files if _join(plugin.path, name) in texts}
    licence = detect_licence(
        frontmatter_licence=None, plugin_licence=_plugin_licence(texts, _join(plugin.path, PLUGIN_MANIFEST)
                                                                 if PLUGIN_MANIFEST in plugin.files else None,
                                                                 opened.plugin),
        repository_files={path: texts[path] for path in _licence_candidates(snapshot, plugin.path) if path in texts})
    found = []
    for server, raw in servers_in_plugin(files).items():
        try:
            spec, problem = launch_spec(server, raw), None
        except SkillCatalogError as error:
            spec, problem = None, error.as_detail()
        security = summary(scan(SKILL_KIND_MCP_SERVER, files, executable=set(), scripts_allowed=False,
                                licence=licence.spdx, launch_spec=spec)) if spec else None
        found.append({
            "kind": SKILL_KIND_MCP_SERVER, "path": plugin.path, "name": server, "launch_spec": spec,
            "security": security,
            "problem": problem, "importable": problem is None, "files": list(plugin.files),
            "licence": {"spdx": licence.spdx, "source": licence.source,
                        "allowed": settings.licence_allowed(licence.spdx)},
            "existing": await _existing(db, server, opened.url, plugin.path),
        })
    return found


def _tracking(value: Any, ref: str) -> str:
    mode = str(value or TRACKING_PINNED).strip().lower()
    if mode not in TRACKING_MODES:
        raise SkillCatalogError("skill_tracking_mode_invalid", 422)
    if mode == TRACKING_FOLLOW and (COMMIT_PATTERN.match(ref) or ref == "HEAD"):
        raise SkillCatalogError("skill_follow_requires_branch", 422,
                                message="Follow needs a branch or tag; a commit can only be pinned.")
    return mode


async def _category_key(db: AsyncSession, category_id: Any) -> str:
    category = await db.get(SkillCategory, str(category_id or ""))
    if category is None:
        raise SkillCatalogError("skill_category_required", 422, message="Choose a category.")
    return category.key


async def upstream_files(snapshot: RepoSnapshot, kind: str, path: str, names: list[str] | None = None
                         ) -> list[BundleFile]:
    """The files of one item at the snapshot's commit, with the bundled LICENSE (the upstream bundle)."""
    if kind == SKILL_KIND_MCP_SERVER:
        relative = [name for name in (PLUGIN_MANIFEST, MCP_FILE) if _join(path, name) in snapshot.entries]
    else:
        relative = names if names is not None else [
            item[len(path) + 1:] if path else item for item in snapshot.paths()
            if (item.startswith(f"{path}/") if path else True)]
    licence = _licence_candidates(snapshot, path)
    wanted = [_join(path, name) for name in relative] + licence
    texts = await _texts(snapshot, wanted)
    files = [BundleFile(name, texts[_join(path, name)],
                        snapshot.entries[_join(path, name)].mode == MODE_EXECUTABLE) for name in relative]
    if licence and not any(item.path in LICENCE_FILE_NAMES for item in files):
        files.append(BundleFile("LICENSE", texts[licence[0]]))
    return files


async def record_snapshot(db: AsyncSession, source: SkillSource, path: str, commit: str,
                          files: list[BundleFile]) -> SkillUpstreamSnapshot:
    existing = (await db.execute(select(SkillUpstreamSnapshot).where(
        SkillUpstreamSnapshot.source_id == source.id, SkillUpstreamSnapshot.path == path,
        SkillUpstreamSnapshot.commit == commit))).scalar_one_or_none()
    if existing is not None:
        return existing
    await store_blobs(db, files)
    entries = manifest(files)
    snapshot = SkillUpstreamSnapshot(source_id=source.id, path=path, commit=commit, files=entries,
                                     bundle_digest=bundle_digest(entries), fetched_at=utc_now())
    db.add(snapshot)
    await db.flush()
    return snapshot


def _licence_of(files: list[BundleFile], plugin_licence: Any = None) -> str | None:
    texts = {item.path: item.content for item in files}
    frontmatter_licence = None
    if SKILL_FILE in texts:
        try:
            frontmatter_licence = parse_skill_md(texts[SKILL_FILE]).frontmatter.get("license")
        except SkillSpecError:
            frontmatter_licence = None
    return detect_licence(frontmatter_licence=frontmatter_licence, plugin_licence=plugin_licence,
                          repository_files={path: texts[path] for path in LICENCE_FILE_NAMES if path in texts}).spdx


async def import_git(db: AsyncSession, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
    settings = await load_settings(db)
    target = git_target(payload, settings)
    commit = str(payload.get("commit") or "")
    if not COMMIT_PATTERN.match(commit):
        raise SkillCatalogError("skill_import_commit_required", 422,
                                message="Import the commit the inspect showed (inspect first).")
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    if not items or len(items) > MAX_IMPORT_ITEMS:
        raise SkillCatalogError("skill_import_items_invalid", 422, message=f"Select 1-{MAX_IMPORT_ITEMS} items.")
    created: list[dict[str, Any]] = []
    async with open_target(db, target, settings, commit if target.marketplace_plugin is None else None) as opened:
        if target.marketplace_plugin is not None and opened.plugin and opened.plugin.get(
                "marketplace_commit") != commit and opened.url == target.url:
            raise SkillCatalogError("skill_import_commit_moved", 409, commit=opened.plugin.get("marketplace_commit"))
        snapshot = opened.snapshot
        source = await git_source(db, url=opened.url, ref=opened.ref, base_path=opened.base_path,
                                  named_connection_id=target.named_connection_id if opened.url == target.url
                                  else None, trust=payload.get("trust"), label=payload.get("label"),
                                  actor_id=actor_id)
        layout = find_layout(snapshot.paths(), opened.base_path)
        known_skills = {item.path: item for item in layout.skills}
        known_plugins = {item.path: item for item in layout.plugins}
        for raw in items:
            item = raw if isinstance(raw, dict) else {}
            kind = str(item.get("kind") or SKILL_KIND_SKILL)
            path = normalize_repo_path(item.get("path") or "")
            if kind == SKILL_KIND_SKILL and path in known_skills:
                name = known_skills[path].name
                files = await upstream_files(snapshot, kind, path, list(known_skills[path].files))
            elif kind == SKILL_KIND_MCP_SERVER and path in known_plugins:
                name = str(item.get("name") or "")
                files = await upstream_files(snapshot, kind, path)
            else:
                raise SkillCatalogError("skill_import_item_not_found", 422, path=path, kind=kind)
            created.append(await _import_item(
                db, source=source, kind=kind, name=name, path=path, commit=snapshot.commit, files=files,
                item=item, ref=opened.ref, plugin=opened.plugin, actor_id=actor_id))
    return {"source_id": source.id, "commit": snapshot.commit, "imported": created}


async def _import_item(db: AsyncSession, *, source: SkillSource, kind: str, name: str, path: str, commit: str,
                       files: list[BundleFile], item: dict[str, Any], ref: str, plugin: dict[str, Any] | None,
                       actor_id: str) -> dict[str, Any]:
    existing = await _existing(db, name, source.url or "", path)
    if existing is not None:
        code = "skill_import_use_update" if existing["relation"] == "update" else "skill_name_exists"
        raise SkillCatalogError(code, 409, name=name, skill_id=existing["skill_id"])
    tracking = _tracking(item.get("tracking_mode"), ref)
    category_id = str(item.get("category_id") or "")
    category_key = await _category_key(db, category_id)
    snapshot_row = await record_snapshot(db, source, path, commit, files)
    spec = None
    if kind == SKILL_KIND_MCP_SERVER:
        servers = servers_in_plugin({entry.path: entry.content for entry in files})
        if name not in servers:
            raise SkillCatalogError("skill_import_item_not_found", 422, path=path, kind=kind, name=name)
        spec = launch_spec(name, servers[name])
    skill = Skill(name=name, kind=kind, category=category_key, category_id=category_id,
                  tags=sorted({str(tag).strip().lower() for tag in item.get("tags") or [] if str(tag).strip()}),
                  source_id=source.id, upstream_path=path, tracking_mode=tracking,
                  pinned_commit=commit if tracking == TRACKING_PINNED else None, owner_id=actor_id, source="custom")
    db.add(skill)
    await db.flush()
    row = await new_draft_row(db, skill, actor_id=actor_id, note=f"Imported from {source.label} @ {commit[:8]}",
                              base_version=None)
    db.add(row)
    plugin_licence = (plugin or {}).get("license")
    await write_content(db, skill, row, VersionContent(
        files=files, extension={}, category_id=category_id, licence_spdx=_licence_of(files, plugin_licence),
        launch_spec=spec, available_platform_chat=kind == SKILL_KIND_SKILL))
    set_upstream(row, UpstreamRef(source.id, path, commit, snapshot_row.bundle_digest))
    await db.flush()
    db.add(AuditLog(user_id=actor_id, action=AUDIT_IMPORTED, resource_type="skill", resource_id=skill.id,
                    details={"source_id": source.id, "path": path, "commit": commit, "version": row.version,
                             "kind": kind}))
    return {"skill_id": skill.id, "name": name, "kind": kind, "version": row.version, "path": path}


async def import_upload(db: AsyncSession, *, filename: str, data: bytes, category_id: Any, tags: Any,
                        actor_id: str) -> dict[str, Any]:
    try:
        uploaded = read_upload(filename, data)
    except BundleError as error:
        raise SkillCatalogError(error.code, 422, message=error.message, **error.details) from None
    if not uploaded.folder:
        raise SkillCatalogError("skill_spec_invalid", 422, issues=[
            {"code": "skill_name_missing", "severity": "error", "field": "name", "message": "Give the skill a name."}])
    issue = name_issue(uploaded.folder)
    if issue is not None:
        raise SkillCatalogError("skill_spec_invalid", 422, issues=[issue.as_dict()])
    source = await upload_source(db, actor_id=actor_id)
    skill = (await db.execute(select(Skill).where(Skill.name == uploaded.folder))).scalar_one_or_none()
    if skill is not None and skill.kind != SKILL_KIND_SKILL:
        raise SkillCatalogError("skill_name_exists", 409, name=uploaded.folder, skill_id=skill.id)
    if skill is not None:
        open_row = (await db.execute(select(SkillVersion.version).where(
            SkillVersion.skill_id == skill.id, SkillVersion.state.in_(["draft", "in_review"])))).first()
        if open_row is not None:
            raise SkillCatalogError("skill_draft_exists", 409, version=open_row[0])
        category_id = category_id or skill.category_id
    category_key = await _category_key(db, category_id)
    if skill is None:
        skill = Skill(name=uploaded.folder, kind=SKILL_KIND_SKILL, category=category_key,
                      category_id=str(category_id), owner_id=actor_id,
                      source="custom", source_id=source.id,
                      tags=sorted({str(tag).strip().lower() for tag in tags or [] if str(tag).strip()}))
        db.add(skill)
        await db.flush()
    published = await db.get(SkillVersion, skill.published_version_id) if skill.published_version_id else None
    row = await new_draft_row(db, skill, actor_id=actor_id, note=f"Uploaded {filename[:120]}",
                              base_version=published.version if published else None)
    db.add(row)
    await write_content(db, skill, row, VersionContent(
        files=uploaded.files, extension=dict(published.extension) if published else {},
        category_id=str(category_id), licence_spdx=_licence_of(uploaded.files),
        available_platform_chat=published.available_platform_chat if published else True,
        available_octryx_claude=published.available_octryx_claude if published else True))
    db.add(AuditLog(user_id=actor_id, action=AUDIT_IMPORTED, resource_type="skill", resource_id=skill.id,
                    details={"source_id": source.id, "upload": filename[:200], "version": row.version}))
    await db.flush()
    return {"skill_id": skill.id, "name": skill.name, "kind": skill.kind, "version": row.version}


__all__ = ["AUDIT_IMPORTED", "import_git", "import_upload", "inspect_git", "open_target", "record_snapshot",
           "upstream_files"]
