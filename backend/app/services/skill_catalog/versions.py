"""Writing the content of a skill version: bundle files, spec validation, digests, listing columns.

:func:`write_content` is the one writer of reviewed content on a draft. It refuses a bundle that breaks the
limits or the Agent Skills spec (``skill_spec_invalid`` with the issues), stores the blobs, sets the parsed
frontmatter/body, the manifest, the bundle digest and the **content digest** — the digest a submit freezes and an
approval binds. The content digest covers everything that changes what an agent receives or who receives it
(files, extension, category, availability, licence, scripts permission, acknowledged findings, launch spec,
upstream provenance, merge state).

:func:`sync_identity` copies the published version onto the identity row's listing columns (published version,
category, surfaces).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Skill, SkillCategory, SkillVersion
from ...models.agent.skill_catalog import SKILL_KIND_MCP_SERVER
from ...time_utils import utc_now
from .bundle import BundleError, BundleFile, bundle_digest, check_limits, manifest, normalize_path, store_blobs
from .errors import SkillCatalogError
from .extension import normalize_extension
from .mcp_entry import launch_spec, normalize_launch_spec, servers_in_plugin
from .scanner import scan, summary
from .spec import SKILL_FILE, SkillSpecError, name_issue, parse_skill_md, validate_skill

MAX_NOTE_CHARS = 500

@dataclass(slots=True)
class VersionContent:
    files: list[BundleFile]
    extension: dict[str, Any]
    category_id: str | None
    available_platform_chat: bool = True
    available_octryx_claude: bool = True
    licence_spdx: str | None = None
    scripts_allowed: bool = False
    scripts_reason: str | None = None
    acknowledged_findings: list[str] = field(default_factory=list)
    launch_spec: dict[str, Any] | None = None


@dataclass(slots=True)
class UpstreamRef:
    source_id: str
    path: str
    commit: str
    bundle_digest: str


def note_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text[:MAX_NOTE_CHARS] or None


def content_of(row: SkillVersion, files: list[BundleFile]) -> VersionContent:
    return VersionContent(
        files=files, extension=dict(row.extension or {}), category_id=row.category_id,
        available_platform_chat=bool(row.available_platform_chat),
        available_octryx_claude=bool(row.available_octryx_claude), licence_spdx=row.licence_spdx,
        scripts_allowed=bool(row.scripts_allowed), scripts_reason=row.scripts_reason,
        acknowledged_findings=list(row.acknowledged_findings or []),
        launch_spec=dict(row.launch_spec) if isinstance(row.launch_spec, dict) else None,
    )


def content_digest(row: SkillVersion) -> str:
    payload = {
        "files": [[entry["path"], entry["sha256"], entry.get("kind")] for entry in row.files or []],
        "extension": row.extension or {},
        "category_id": row.category_id,
        "available": [bool(row.available_platform_chat), bool(row.available_octryx_claude)],
        "licence": row.licence_spdx,
        "scripts": [bool(row.scripts_allowed), row.scripts_reason or ""],
        "acknowledged": sorted(row.acknowledged_findings or []),
        "launch_spec": row.launch_spec,
        "upstream": [row.upstream_source_id, row.upstream_path, row.upstream_commit, row.upstream_bundle_digest],
        "merge": (row.merge_report or {}).get("resolutions") if isinstance(row.merge_report, dict) else None,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _normalized_files(files: list[BundleFile]) -> list[BundleFile]:
    try:
        return check_limits([BundleFile(normalize_path(item.path), item.content, item.executable) for item in files])
    except BundleError as error:
        raise SkillCatalogError(error.code, 422, message=error.message, **error.details) from None


async def _category(db: AsyncSession, category_id: str | None) -> SkillCategory:
    category = await db.get(SkillCategory, category_id) if category_id else None
    if category is None:
        raise SkillCatalogError("skill_category_required", 422, message="Choose a category.")
    if category.archived_at is not None:
        raise SkillCatalogError("skill_category_archived", 422, message="The category is archived.")
    return category


def _checked_launch_spec(skill: Skill, content: VersionContent, texts: dict[str, str]) -> dict[str, Any]:
    """The launch spec of an MCP server entry: command and args come from the files, never from the request."""
    servers = servers_in_plugin(texts)
    requested = content.launch_spec or {"server": skill.name}
    if str(requested.get("server") or "") != skill.name or skill.name not in servers:
        raise SkillCatalogError("skill_mcp_launch_spec_invalid", 422,
                                message="The entry's .mcp.json must define the server named like the entry.")
    return normalize_launch_spec(requested, upstream=launch_spec(skill.name, servers[skill.name]))


def _check_availability(skill: Skill, content: VersionContent) -> None:
    """Availability invariants: an MCP server entry never reaches platform chat (a local stdio server
    cannot run there), and a name outside the Agent Skills spec is never delivered to Claude Code."""
    if skill.kind == SKILL_KIND_MCP_SERVER and content.available_platform_chat:
        raise SkillCatalogError("skill_mcp_not_on_platform_chat", 422,
                                message="An MCP server entry is delivered to octryx-claude only.")
    if content.available_octryx_claude and name_issue(skill.name) is not None:
        raise SkillCatalogError("skill_name_not_deliverable", 422,
                                message="Only names that follow the Agent Skills spec are delivered to Claude Code.")


async def write_content(
    db: AsyncSession, skill: Skill, row: SkillVersion, content: VersionContent
) -> None:
    """Validate and write ``content`` onto the draft ``row``; flushes. Raises :class:`SkillCatalogError`.

    A stored name outside the spec is kept as a warning; such a skill stays in platform chat but is never delivered
    to Claude Code (the manifest withholds invalid names).
    """
    files = _normalized_files(content.files)
    await _category(db, content.category_id)
    texts = {item.path: item.content for item in files}
    report: dict[str, Any] = {"spec": []}
    launch = content.launch_spec
    if skill.kind == SKILL_KIND_MCP_SERVER:
        launch = _checked_launch_spec(skill, content, texts)
        row.frontmatter, row.body = {}, ""
    else:
        if SKILL_FILE not in texts:
            raise SkillCatalogError("skill_md_missing", 422, message="A skill needs a SKILL.md at its root.")
        try:
            parsed = parse_skill_md(texts[SKILL_FILE])
        except SkillSpecError as error:
            raise SkillCatalogError("skill_spec_invalid", 422, issues=[
                {"code": error.code, "severity": "error", "field": "frontmatter", "message": error.message}]) from None
        issues = validate_skill(parsed.frontmatter, parsed.body, folder_name=skill.name,
                                skill_md_text=texts[SKILL_FILE], paths=sorted(texts))
        if name_issue(skill.name) is not None:  # a name outside the spec stays editable (never delivered)
            issues = [replace(issue, severity="warning") if issue.field == "name" else issue for issue in issues]
        errors = [issue.as_dict() for issue in issues if issue.severity == "error"]
        if errors:
            raise SkillCatalogError("skill_spec_invalid", 422, issues=errors)
        report["spec"] = [issue.as_dict() for issue in issues]
        row.frontmatter, row.body = parsed.frontmatter, parsed.body
    _check_availability(skill, content)
    findings = scan(skill.kind, texts, executable={item.path for item in files if item.executable},
                    scripts_allowed=bool(content.scripts_allowed), licence=content.licence_spdx, launch_spec=launch)
    report.update(findings=findings, summary=summary(findings))
    acknowledgeable = {item["id"] for item in findings if item["acknowledge"]}
    await store_blobs(db, files)
    row.files = manifest(files)
    row.bundle_digest = bundle_digest(row.files)
    row.extension = normalize_extension(content.extension)
    row.category_id = content.category_id
    row.available_platform_chat = bool(content.available_platform_chat)
    row.available_octryx_claude = bool(content.available_octryx_claude)
    row.licence_spdx = (str(content.licence_spdx).strip()[:64] or None) if content.licence_spdx else None
    row.scripts_allowed = bool(content.scripts_allowed)
    row.scripts_reason = note_text(content.scripts_reason) if content.scripts_allowed else None
    # Only findings that exist and take an acknowledgement can be acknowledged; stale ids fall away on save.
    row.acknowledged_findings = sorted({str(item) for item in content.acknowledged_findings} & acknowledgeable)
    row.launch_spec = launch
    row.security_report = report
    row.digest = content_digest(row)
    row.updated_at = utc_now()
    await db.flush()


def set_upstream(row: SkillVersion, upstream: UpstreamRef | None) -> None:
    if upstream is None:
        return
    row.upstream_source_id, row.upstream_path = upstream.source_id, upstream.path
    row.upstream_commit, row.upstream_bundle_digest = upstream.commit, upstream.bundle_digest
    row.digest = content_digest(row)


async def next_version_number(db: AsyncSession, skill_id: str) -> int:
    latest = (await db.execute(select(func.max(SkillVersion.version)).where(SkillVersion.skill_id == skill_id)))
    return int(latest.scalar_one_or_none() or 0) + 1


async def new_draft_row(
    db: AsyncSession, skill: Skill, *, actor_id: str | None, note: Any, base_version: int | None
) -> SkillVersion:
    now = utc_now()
    return SkillVersion(
        skill_id=skill.id, version=await next_version_number(db, skill.id), state="draft", digest="",
        bundle_digest="", files=[], frontmatter={}, body="", extension={}, created_by=actor_id,
        note=note_text(note), base_version=base_version, created_at=now, updated_at=now,
    )


async def sync_identity(db: AsyncSession, skill: Skill, published: SkillVersion | None) -> None:
    """Copy the published version onto the identity row's listing columns."""
    if published is None:
        skill.published_version_id = None
        skill.available_platform_chat = skill.available_octryx_claude = False
        return
    category = await db.get(SkillCategory, published.category_id) if published.category_id else None
    skill.published_version_id = published.id
    skill.category_id = published.category_id
    skill.category = category.key if category is not None else (skill.category or "uncategorized")
    skill.available_platform_chat = bool(published.available_platform_chat)
    skill.available_octryx_claude = bool(published.available_octryx_claude)


__all__ = [
    "UpstreamRef",
    "VersionContent",
    "content_digest",
    "content_of",
    "new_draft_row",
    "next_version_number",
    "note_text",
    "set_upstream",
    "sync_identity",
    "write_content",
]
