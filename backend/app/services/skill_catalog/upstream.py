"""Upstream renewal: check, update draft (3-way merge), pin/follow, scheduled checks.

- **Change detection is per skill path**: the upstream bundle digest at the latest commit of the tracked ref is
  compared with the reference version's ``upstream_bundle_digest``; repository commits that do not touch the
  skill never raise "update available". A source pinned to a commit is compared with the remote's default branch.
- **Moved folder**: when the tracked path is gone, the repository is searched for the skill by name (a folder
  whose ``SKILL.md`` has the same frontmatter ``name``; for an MCP server entry, a plugin defining the server).
  Exactly one match → the update follows it and publishing moves the tracked path; none or several →
  ``skill_upstream_path_missing`` and the admin picks the path.
- **Update** builds a new draft from the 3-way merge (base = the upstream snapshot the reference version came
  from, ours = the reference version, theirs = the new upstream) with the merge report; it goes through four-eyes
  review like every draft. ``pinned`` informs only (the update is an explicit admin action that moves the pin at
  publish); ``follow`` lets the scheduled check create the update draft by itself and notifies the
  owner.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, Skill, SkillSource, SkillUpstreamSnapshot, SkillVersion
from ...models.agent.skill_catalog import (
    SKILL_KIND_MCP_SERVER,
    SOURCE_KIND_GIT,
    TRACKING_FOLLOW,
    TRACKING_MODES,
    TRACKING_PINNED,
)
from ...time_utils import ensure_utc, utc_now
from .bundle import BundleFile, bundle_digest, bundle_files, decode_text, manifest
from .errors import SkillCatalogError
from .git_source import COMMIT_PATTERN, RepoSnapshot, git_fetcher, normalize_repository_url
from .importer import record_snapshot, upstream_files
from .layout import find_layout
from .lifecycle import open_version, published_version
from .mcp_entry import MCP_FILE, PLUGIN_MANIFEST, launch_spec, servers_in_plugin
from .merge import merge_bundle
from .settings import load_settings
from .sources import source_token
from .spec import SKILL_FILE, SkillSpecError, parse_skill_md
from .versions import UpstreamRef, content_of, new_draft_row, set_upstream, write_content

AUDIT_CHECKED = "skill_catalog.upstream_checked"
AUDIT_UPDATE_DRAFT = "skill_catalog.update_draft_created"
AUDIT_TRACKING = "skill_catalog.tracking_changed"
logger = logging.getLogger(__name__)


def _join(root: str, name: str) -> str:
    return f"{root}/{name}" if root else name


async def _reference(db: AsyncSession, skill: Skill) -> SkillVersion:
    """The version the update compares with: the published one, else the latest one."""
    published = await published_version(db, skill)
    if published is not None:
        return published
    latest = (await db.execute(select(SkillVersion).where(SkillVersion.skill_id == skill.id)
                               .order_by(SkillVersion.version.desc()).limit(1))).scalar_one_or_none()
    if latest is None:
        raise SkillCatalogError("skill_version_not_found", 404)
    return latest


async def _tracked_source(db: AsyncSession, skill: Skill) -> SkillSource:
    source = await db.get(SkillSource, skill.source_id) if skill.source_id else None
    if source is None or source.kind != SOURCE_KIND_GIT or skill.upstream_path is None:
        raise SkillCatalogError("skill_not_tracked", 409, message="This skill has no Git upstream.")
    return source


def compare_ref(source: SkillSource) -> str:
    ref = str(source.ref or "HEAD")
    return "HEAD" if COMMIT_PATTERN.match(ref) else ref


async def _find_moved(snapshot: RepoSnapshot, skill: Skill) -> str:
    paths = snapshot.paths()
    if skill.kind == SKILL_KIND_MCP_SERVER:
        layout = find_layout(paths, "")
        wanted = [_join(plugin.path, name) for plugin in layout.plugins for name in plugin.files]
        texts = {path: decode_text(path, data) for path, data in (await snapshot.read_many(wanted)).items()}
        matches = [plugin.path for plugin in layout.plugins if skill.name in servers_in_plugin({
            name: texts[_join(plugin.path, name)] for name in plugin.files})]
    else:
        candidates = [item for item in find_layout(paths, "").skills if item.name == skill.name]
        texts = await snapshot.read_many([_join(item.path, SKILL_FILE) for item in candidates])
        matches = []
        for item in candidates:
            try:
                name = parse_skill_md(decode_text(item.path, texts[_join(item.path, SKILL_FILE)])).frontmatter.get(
                    "name")
            except SkillSpecError:
                continue
            if name == skill.name:
                matches.append(item.path)
    if len(matches) != 1:
        raise SkillCatalogError("skill_upstream_path_missing", 409, path=skill.upstream_path, candidates=matches,
                                message="The tracked folder is gone upstream; pick the new path.")
    return matches[0]


def _exists(snapshot: RepoSnapshot, path: str, kind: str) -> bool:
    marker = (_join(path, MCP_FILE), _join(path, PLUGIN_MANIFEST)) if kind == SKILL_KIND_MCP_SERVER else (
        _join(path, SKILL_FILE),)
    return any(item in snapshot.entries for item in marker)


async def _latest(db: AsyncSession, skill: Skill, source: SkillSource, snapshot: RepoSnapshot,
                  path_override: str | None) -> tuple[str, list[BundleFile], str | None]:
    path = path_override if path_override is not None else str(skill.upstream_path or "")
    moved_from = None
    if not _exists(snapshot, path, skill.kind):
        moved_from, path = path, await _find_moved(snapshot, skill)
    names = None
    if skill.kind != SKILL_KIND_MCP_SERVER:
        layout = find_layout(snapshot.paths(), path)
        found = next((item for item in layout.skills if item.path == path), None)
        names = list(found.files) if found is not None else None
    return path, await upstream_files(snapshot, skill.kind, path, names), moved_from


async def check_skill(db: AsyncSession, skill: Skill, *, actor_id: str | None,
                      path_override: str | None = None) -> dict[str, Any]:
    """Compare the reference version with the upstream; stores and returns ``skill.upstream_status``."""
    source = await _tracked_source(db, skill)
    settings = await load_settings(db)
    reference = await _reference(db, skill)
    try:
        url = normalize_repository_url(source.url, settings.allowed_hosts)
        token = await source_token(db, source.named_connection_id)
        fetcher = git_fetcher()
        latest = await fetcher.resolve(url, compare_ref(source), token=token)
        async with fetcher.open(url, latest, token=token) as snapshot:
            path, files, moved_from = await _latest(db, skill, source, snapshot, path_override)
    except SkillCatalogError as error:
        source.last_error, source.last_checked_at = error.code, utc_now()
        skill.upstream_status = {**(skill.upstream_status or {}), "error": error.code,
                                 "checked_at": utc_now().isoformat()}
        await db.flush()
        raise
    digest = bundle_digest(manifest(files))
    status = {
        "checked_at": utc_now().isoformat(), "compare_ref": compare_ref(source), "latest_commit": latest,
        "current_commit": reference.upstream_commit, "path": path,
        "path_moved": {"from": moved_from, "to": path} if moved_from else None, "upstream_digest": digest,
        "update_available": digest != reference.upstream_bundle_digest or path != reference.upstream_path,
        "reference_version": reference.version, "error": None,
    }
    skill.upstream_status = status
    source.last_checked_at, source.last_seen_commit, source.last_error = utc_now(), latest, None
    if actor_id:
        db.add(AuditLog(user_id=actor_id, action=AUDIT_CHECKED, resource_type="skill", resource_id=skill.id,
                        details={k: status[k] for k in ("latest_commit", "update_available", "path_moved")}))
    await db.flush()
    return status


def _carried_launch_spec(reference: SkillVersion, files: dict[str, str], name: str) -> dict[str, Any] | None:
    """The reviewed launch-spec choices that stay valid: the digest only for the same image, known env mappings."""
    old = reference.launch_spec if isinstance(reference.launch_spec, dict) else None
    if old is None:
        return None
    servers = servers_in_plugin(files)
    if name not in servers:
        return {"server": name}
    new = launch_spec(name, servers[name])
    carried: dict[str, Any] = {"server": name}
    if old.get("image") == new.get("image") and old.get("image_digest"):
        carried["image_digest"] = old["image_digest"]
    known = set(new.get("passthrough") or []) | set(new.get("env_names") or [])
    carried["env_connections"] = {key: value for key, value in (old.get("env_connections") or {}).items()
                                  if key in known}
    return carried


async def update_from_upstream(db: AsyncSession, skill: Skill, *, actor_id: str | None, audit_user: str,
                               path_override: str | None = None, automatic: bool = False) -> SkillVersion:
    """A new draft merging the latest upstream into the reference version (3-way)."""
    opened = await open_version(db, skill)
    if opened is not None:
        raise SkillCatalogError("skill_draft_exists", 409, version=opened.version, state=opened.state)
    source = await _tracked_source(db, skill)
    settings = await load_settings(db)
    reference = await _reference(db, skill)
    base_row = (await db.execute(select(SkillUpstreamSnapshot).where(
        SkillUpstreamSnapshot.source_id == reference.upstream_source_id,
        SkillUpstreamSnapshot.path == reference.upstream_path,
        SkillUpstreamSnapshot.commit == reference.upstream_commit))).scalar_one_or_none()
    if base_row is None:
        raise SkillCatalogError("skill_merge_base_missing", 409,
                                message="The upstream snapshot of this version is missing; re-import it.")
    url = normalize_repository_url(source.url, settings.allowed_hosts)
    token = await source_token(db, source.named_connection_id)
    fetcher = git_fetcher()
    latest = await fetcher.resolve(url, compare_ref(source), token=token)
    async with fetcher.open(url, latest, token=token) as snapshot:
        path, theirs_files, moved_from = await _latest(db, skill, source, snapshot, path_override)
    theirs_digest = bundle_digest(manifest(theirs_files))
    if theirs_digest == reference.upstream_bundle_digest and path == reference.upstream_path:
        raise SkillCatalogError("skill_up_to_date", 409, commit=latest)
    base_files = await bundle_files(db, base_row.files)
    ours_files = await bundle_files(db, reference.files)
    executable = {item.path for item in [*ours_files, *theirs_files] if item.executable}
    merged = merge_bundle({item.path: item.content for item in base_files},
                          {item.path: item.content for item in ours_files},
                          {item.path: item.content for item in theirs_files})
    snapshot_row = await record_snapshot(db, source, path, latest, theirs_files)
    row = await new_draft_row(db, skill, actor_id=actor_id, base_version=reference.version,
                              note=f"Upstream update {str(reference.upstream_commit or '')[:8]} → {latest[:8]}")
    db.add(row)
    content = content_of(reference, [BundleFile(name, text, name in executable)
                                     for name, text in sorted(merged["files"].items())])
    if skill.kind == SKILL_KIND_MCP_SERVER:
        content.launch_spec = _carried_launch_spec(reference, merged["files"], skill.name)
    await write_content(db, skill, row, content)
    row.merge_report = {**merged["report"], "base_commit": reference.upstream_commit, "theirs_commit": latest,
                        "from_version": reference.version,
                        "path_moved": {"from": moved_from, "to": path} if moved_from else None}
    set_upstream(row, UpstreamRef(source.id, path, latest, snapshot_row.bundle_digest))
    db.add(AuditLog(user_id=audit_user, action=AUDIT_UPDATE_DRAFT, resource_type="skill", resource_id=skill.id,
                    details={"version": row.version, "from": reference.upstream_commit, "to": latest,
                             "conflicts": len(merged["report"]["conflicts"]), "automatic": automatic}))
    await db.flush()
    return row


async def set_tracking(db: AsyncSession, skill: Skill, mode: Any, *, actor_id: str) -> Skill:
    value = str(mode or "").strip().lower()
    if value not in TRACKING_MODES:
        raise SkillCatalogError("skill_tracking_mode_invalid", 422)
    source = await _tracked_source(db, skill)
    if value == TRACKING_FOLLOW and (COMMIT_PATTERN.match(str(source.ref or "")) or str(source.ref) == "HEAD"):
        raise SkillCatalogError("skill_follow_requires_branch", 422,
                                message="Follow needs a branch or tag; this source is pinned to a commit.")
    reference = await _reference(db, skill)
    skill.tracking_mode = value
    skill.pinned_commit = reference.upstream_commit if value == TRACKING_PINNED else None
    db.add(AuditLog(user_id=actor_id, action=AUDIT_TRACKING, resource_type="skill", resource_id=skill.id,
                    details={"tracking_mode": value, "pinned_commit": skill.pinned_commit}))
    await db.flush()
    return skill


def _due(source: SkillSource, hours: int) -> bool:
    if source.last_checked_at is None:
        return True
    elapsed = utc_now() - ensure_utc(source.last_checked_at).replace(tzinfo=None)
    return elapsed.total_seconds() >= hours * 3600


async def run_scheduled_checks(db: AsyncSession, *, force: bool = False) -> dict[str, int]:
    """One pass of the scheduled check (every source due by ``update_check_hours``); commits per skill."""
    from ..team_notification import create_notification

    settings = await load_settings(db)
    summary = {"sources": 0, "skills": 0, "updates": 0, "drafts": 0, "errors": 0}
    if settings.update_check_hours <= 0 and not force:
        return summary
    sources = (await db.execute(select(SkillSource).where(SkillSource.kind == SOURCE_KIND_GIT))).scalars().all()
    for source in sources:
        if not force and not _due(source, settings.update_check_hours):
            continue
        summary["sources"] += 1
        skills = (await db.execute(select(Skill).where(Skill.source_id == source.id))).scalars().all()
        for skill in skills:
            summary["skills"] += 1
            try:
                status = await check_skill(db, skill, actor_id=None)
            except SkillCatalogError as error:
                summary["errors"] += 1
                logger.info("skill upstream check refused", extra={"skill": skill.name, "code": error.code})
                await db.commit()
                continue
            await db.commit()
            if not status["update_available"]:
                continue
            summary["updates"] += 1
            if skill.tracking_mode != TRACKING_FOLLOW or await open_version(db, skill) is not None:
                continue
            owner = skill.owner_id or source.created_by
            try:
                row = await update_from_upstream(db, skill, actor_id=None, audit_user=owner, automatic=True)
                if owner:
                    await create_notification(
                        db, user_id=owner, notification_type="skill_update_draft",
                        title=f"Skill update ready for review: {skill.name} v{row.version}",
                        body=f"Upstream {status['latest_commit'][:8]}; "
                             f"{len((row.merge_report or {}).get('conflicts') or [])} conflict(s).",
                        link="/chat?area=workflows&tab=skills")
                await db.commit()
                summary["drafts"] += 1
            except SkillCatalogError as error:
                await db.rollback()
                summary["errors"] += 1
                logger.info("skill update draft refused", extra={"skill": skill.name, "code": error.code})
    return summary


__all__ = ["check_skill", "compare_ref", "run_scheduled_checks", "set_tracking", "update_from_upstream"]
