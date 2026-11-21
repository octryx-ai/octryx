"""Skill versions: draft → in_review → published → retired, four-eyes publish (the policy-set pattern).

- **Edit** continues the open draft (at most one per skill) or starts one from the published version.
- **Save** needs ``If-Match: <draft digest>`` (428 without, 409 ``skill_draft_conflict`` when stale). The check is
  a conditional ``UPDATE … WHERE digest = <If-Match>`` that holds the row lock until the commit, so of two saves
  with the same ``If-Match`` the second one is refused instead of overwriting the first. Each save reruns the spec
  validation and the security scanner.
- **Submit** refuses while merge conflicts are open, freezes the bundle and opens a governance ``Approval``
  (``workspace_id`` NULL: platform admins) whose action binds the version id **and** its content digest.
- **Publish** needs that approval ``approved`` by a platform admin who is neither the author, the submitter nor
  the requester (``skill_self_approval``), unless the platform approval rule allows self-approval (the shared
  gate ``services.governance.four_eyes``); then ``publish(..., self_approve=True)`` approves and publishes at once.
  It also refuses open conflicts, unacknowledged high-severity findings, secrets, a licence outside the allowlist
  and an MCP container image without a recorded digest. Publishing retires the previous published version.
- **Retire** withdraws a draft or a version in review; retiring the published version removes the skill from
  every surface (a narrowing, so one admin may do it). **Rollback** creates a new draft from an earlier version.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, AuditLog, Skill, SkillVersion
from ...models.agent.skill_catalog import SKILL_KIND_MCP_SERVER, TRACKING_PINNED
from ...models.runtime.governed_revision import (
    REVISION_STATE_DRAFT,
    REVISION_STATE_IN_REVIEW,
    REVISION_STATE_PUBLISHED,
    REVISION_STATE_RETIRED,
)
from ...time_utils import utc_now
from ..access_control import _user_is_admin
from ..governance.four_eyes import (
    APPROVAL_MODE_FOUR_EYES,
    APPROVAL_MODE_SELF,
    SelfApprovalRefusedError,
    decide_four_eyes,
    record_self_approval_audit,
    self_approve_pending,
)
from .adoption import approval_action
from .bundle import BundleFile, bundle_files
from .categories import get_category, set_tags
from .errors import SkillCatalogError
from .merge import resolved_files
from .settings import LICENCE_INTERNAL, load_settings
from .spec import SKILL_FILE, SkillSpecError, name_issue, parse_skill_md, render_skill_md, replace_frontmatter
from .versions import (
    VersionContent,
    content_digest,
    content_of,
    new_draft_row,
    note_text,
    sync_identity,
    write_content,
)

AUDIT_DRAFT_SAVED = "skill_catalog.draft_saved"
AUDIT_SUBMITTED = "skill_catalog.submitted"
AUDIT_PUBLISHED = "skill_catalog.published"
AUDIT_RETIRED = "skill_catalog.retired"

OPEN_STATES = (REVISION_STATE_DRAFT, REVISION_STATE_IN_REVIEW)
HIGH = "high"


def _audit(db: AsyncSession, actor_id: str | None, action: str, skill: Skill, row: SkillVersion, **details: Any
           ) -> None:
    db.add(AuditLog(user_id=actor_id, action=action, resource_type="skill_version", resource_id=row.id,
                    details={"skill_id": skill.id, "skill": skill.name, "version": row.version, "digest": row.digest,
                             **details}))


def etag(value: str | None) -> str:
    text = str(value or "").strip()
    if text.startswith("W/"):
        text = text[2:]
    return text.strip('"')


async def get_skill(db: AsyncSession, skill_id: str) -> Skill:
    skill = await db.get(Skill, skill_id)
    if skill is None:
        raise SkillCatalogError("skill_not_found", 404)
    return skill


async def get_version(db: AsyncSession, skill: Skill, version: int) -> SkillVersion:
    row = (await db.execute(select(SkillVersion).where(
        SkillVersion.skill_id == skill.id, SkillVersion.version == int(version)))).scalar_one_or_none()
    if row is None:
        raise SkillCatalogError("skill_version_not_found", 404)
    return row


async def list_versions(db: AsyncSession, skill: Skill) -> list[SkillVersion]:
    stmt = select(SkillVersion).where(SkillVersion.skill_id == skill.id).order_by(SkillVersion.version.desc())
    return list((await db.execute(stmt)).scalars())


async def open_version(db: AsyncSession, skill: Skill) -> SkillVersion | None:
    stmt = select(SkillVersion).where(SkillVersion.skill_id == skill.id, SkillVersion.state.in_(OPEN_STATES))
    return (await db.execute(stmt)).scalar_one_or_none()


async def published_version(db: AsyncSession, skill: Skill) -> SkillVersion | None:
    stmt = select(SkillVersion).where(SkillVersion.skill_id == skill.id,
                                      SkillVersion.state == REVISION_STATE_PUBLISHED)
    return (await db.execute(stmt)).scalar_one_or_none()


async def draft_from(db: AsyncSession, skill: Skill, source: SkillVersion, *, actor_id: str | None, note: Any,
                     base_version: int | None) -> SkillVersion:
    """A new draft carrying ``source``'s content and provenance (no merge state)."""
    row = await new_draft_row(db, skill, actor_id=actor_id, note=note, base_version=base_version)
    db.add(row)
    content = content_of(source, await bundle_files(db, source.files))
    await write_content(db, skill, row, content)
    row.upstream_source_id, row.upstream_path = source.upstream_source_id, source.upstream_path
    row.upstream_commit, row.upstream_bundle_digest = source.upstream_commit, source.upstream_bundle_digest
    row.scripts_allowed_by = source.scripts_allowed_by
    row.digest = content_digest(row)
    await db.flush()
    return row


async def start_draft(db: AsyncSession, skill: Skill, *, actor_id: str) -> tuple[SkillVersion, bool]:
    """``(draft, created)``: the open draft continues; otherwise a new one from the published version."""
    opened = await open_version(db, skill)
    if opened is not None:
        if opened.state != REVISION_STATE_DRAFT:
            raise SkillCatalogError("skill_version_in_review", 409, version=opened.version)
        return opened, False
    published = await published_version(db, skill)
    if published is None:
        raise SkillCatalogError("skill_nothing_to_edit", 409, message="Roll back to an earlier version instead.")
    row = await draft_from(db, skill, published, actor_id=actor_id, note=None, base_version=published.version)
    _audit(db, actor_id, AUDIT_DRAFT_SAVED, skill, row, created=True)
    return row, True


async def _claim(db: AsyncSession, row: SkillVersion, expected: str) -> None:
    claimed = await db.execute(
        update(SkillVersion)
        .where(SkillVersion.id == row.id, SkillVersion.state == REVISION_STATE_DRAFT, SkillVersion.digest == expected)
        .values(digest=SkillVersion.digest)
        .execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        await db.refresh(row)
        raise SkillCatalogError("skill_draft_conflict", 409, digest=row.digest, state=row.state)


def _skill_md(current: dict[str, str], payload: dict[str, Any]) -> str | None:
    if isinstance(payload.get("skill_md"), str):
        return payload["skill_md"]
    if not isinstance(payload.get("frontmatter"), dict) and not isinstance(payload.get("body"), str):
        return None
    text = current.get(SKILL_FILE, "")
    try:
        parsed = parse_skill_md(text)
    except SkillSpecError:
        parsed = None
    frontmatter = payload["frontmatter"] if isinstance(payload.get("frontmatter"), dict) else (
        parsed.frontmatter if parsed else {})
    if isinstance(payload.get("body"), str):
        return render_skill_md(frontmatter, payload["body"])
    return replace_frontmatter(text, frontmatter) if parsed else render_skill_md(frontmatter, "")


def _edited_files(files: list[BundleFile], payload: dict[str, Any]) -> list[BundleFile]:
    by_path = {item.path: item for item in files}
    current = {path: item.content for path, item in by_path.items()}
    skill_md = _skill_md(current, payload)
    if skill_md is not None:
        by_path[SKILL_FILE] = BundleFile(SKILL_FILE, skill_md)
    changes = payload.get("files") if isinstance(payload.get("files"), dict) else {}
    for path, content in changes.items():
        if path == SKILL_FILE:
            raise SkillCatalogError("skill_md_via_files", 422, message="Edit SKILL.md through skill_md or the fields.")
        if content is None:
            by_path.pop(str(path), None)
        else:
            previous = by_path.get(str(path))
            by_path[str(path)] = BundleFile(str(path), str(content), previous.executable if previous else False)
    return list(by_path.values())


def _resolved(row: SkillVersion, files: list[BundleFile], resolutions: Any) -> list[BundleFile]:
    """Conflicted files rebuilt from the merge layout with ``resolutions`` (resolve before editing them by hand)."""
    if not isinstance(row.merge_report, dict) or not isinstance(resolutions, dict):
        raise SkillCatalogError("skill_no_merge_to_resolve", 422)
    report = {**row.merge_report, "resolutions": resolutions}
    texts = resolved_files({item.path: item.content for item in files}, report)
    executable = {item.path for item in files if item.executable}
    row.merge_report = report
    return [BundleFile(path, text, path in executable) for path, text in sorted(texts.items())]


async def save_draft(db: AsyncSession, skill: Skill, row: SkillVersion, payload: dict[str, Any], *,
                     if_match: str | None, actor_id: str) -> SkillVersion:
    expected = etag(if_match)
    if not expected:
        raise SkillCatalogError("skill_if_match_required", 428)
    if row.state != REVISION_STATE_DRAFT:
        raise SkillCatalogError("skill_version_not_draft", 409, state=row.state)
    await _claim(db, row, expected)
    files = await bundle_files(db, row.files)
    if "resolutions" in payload:
        files = _resolved(row, files, payload["resolutions"])
    content = content_of(row, _edited_files(files, payload))
    for key in ("category_id", "licence_spdx", "scripts_reason", "launch_spec"):
        if key in payload:
            setattr(content, key, payload[key])
    for key in ("available_platform_chat", "available_octryx_claude", "scripts_allowed"):
        if key in payload:
            setattr(content, key, bool(payload[key]))
    if "extension" in payload:
        content.extension = {**content.extension, **(payload["extension"] or {})}
    if "acknowledged_findings" in payload:
        content.acknowledged_findings = [str(item) for item in payload["acknowledged_findings"] or []]
    if content.scripts_allowed and not str(content.scripts_reason or "").strip():
        raise SkillCatalogError("skill_scripts_reason_required", 422,
                                message="Give a reason for delivering this version's scripts.")
    upstream = (row.upstream_source_id, row.upstream_path, row.upstream_commit, row.upstream_bundle_digest)
    await write_content(db, skill, row, content)
    row.upstream_source_id, row.upstream_path, row.upstream_commit, row.upstream_bundle_digest = upstream
    if content.scripts_allowed and not row.scripts_allowed_by:
        row.scripts_allowed_by = actor_id
    if not content.scripts_allowed:
        row.scripts_allowed_by = None
    if "note" in payload:
        row.note = note_text(payload["note"])
    row.digest = content_digest(row)
    _audit(db, actor_id, AUDIT_DRAFT_SAVED, skill, row, created=False)
    await db.flush()
    return row


def open_conflicts(row: SkillVersion) -> list[str]:
    report = row.merge_report if isinstance(row.merge_report, dict) else {}
    resolutions = report.get("resolutions") if isinstance(report.get("resolutions"), dict) else {}
    return [str(item.get("id")) for item in report.get("conflicts") or []
            if isinstance(item, dict) and str(item.get("id")) not in resolutions]


async def submit(db: AsyncSession, skill: Skill, row: SkillVersion, *, actor_id: str) -> Approval:
    if row.state != REVISION_STATE_DRAFT:
        raise SkillCatalogError("skill_version_not_draft", 409, state=row.state)
    conflicts = open_conflicts(row)
    if conflicts:
        raise SkillCatalogError("skill_draft_has_conflicts", 409, conflicts=conflicts)
    now = utc_now()
    row.state, row.submitted_by, row.submitted_at, row.updated_at = REVISION_STATE_IN_REVIEW, actor_id, now, now
    approval = Approval(requested_by=actor_id, workspace_id=None, action=approval_action(row), status="pending",
                        reason=f"Publish skill {skill.name} version {row.version}")
    db.add(approval)
    await db.flush()
    row.approval_id = approval.id
    _audit(db, actor_id, AUDIT_SUBMITTED, skill, row, approval_id=approval.id)
    await db.flush()
    return approval


@dataclass(frozen=True, slots=True)
class PublishGate:
    approval_id: str
    requested_by: str
    approved_by: str
    single_admin: bool

    @property
    def approval_mode(self) -> str:
        return APPROVAL_MODE_SELF if self.single_admin else APPROVAL_MODE_FOUR_EYES

    def as_dict(self) -> dict[str, Any]:
        return {"status": "approved", "approval_id": self.approval_id, "requested_by": self.requested_by,
                "approved_by": self.approved_by, "single_admin_self_approval": self.single_admin,
                "approval_mode": self.approval_mode}


async def _version_authors(db: AsyncSession, row: SkillVersion) -> set[str]:
    """Everyone who shaped this version: its creator, submitter, script allower and every draft editor."""
    editors = (await db.execute(select(AuditLog.user_id).where(
        AuditLog.action == AUDIT_DRAFT_SAVED, AuditLog.resource_type == "skill_version",
        AuditLog.resource_id == row.id))).scalars().all()
    authors = {row.created_by, row.submitted_by, row.scripts_allowed_by, *editors}
    return {str(item) for item in authors if item}


async def check_publish_gate(db: AsyncSession, row: SkillVersion, approval_id: str | None) -> PublishGate:
    if not approval_id:
        raise SkillCatalogError("skill_approval_required")
    approval = await db.get(Approval, approval_id)
    if approval is None:
        raise SkillCatalogError("skill_approval_missing")
    if approval.action != approval_action(row) or approval.workspace_id is not None or approval.session_id:
        raise SkillCatalogError("skill_approval_mismatched")
    if approval.status != "approved" or not approval.approved_by:
        raise SkillCatalogError("skill_approval_not_approved", approval_status=str(approval.status or ""))
    approver = str(approval.approved_by)
    decision = await decide_four_eyes(db, approval.requested_by, approver, authors=await _version_authors(db, row))
    if not decision.approved:
        raise SkillCatalogError("skill_self_approval")
    if not await _user_is_admin(db, approver):
        raise SkillCatalogError("skill_approver_not_platform_admin")
    record_self_approval_audit(db, decision, resource_type="skill_version", resource_id=row.id,
                               approval_id=approval.id)
    return PublishGate(approval.id, str(approval.requested_by), approver, decision.self_approved)


async def self_approve_review(db: AsyncSession, row: SkillVersion, *, actor_id: str) -> str:
    """The single-step publish: the submitter approves their own pending review (approval rule permitting)."""
    approval = await db.get(Approval, row.approval_id) if row.approval_id else None
    if approval is None:
        raise SkillCatalogError("skill_approval_required")
    try:
        await self_approve_pending(db, approval, actor_id=actor_id)
    except SelfApprovalRefusedError as error:
        raise SkillCatalogError("skill_self_approval", reason=error.code) from None
    return approval.id


def blocking_findings(row: SkillVersion) -> dict[str, list[str]]:
    """Unacknowledged high findings and findings that no acknowledgement clears (``blocks``: secrets)."""
    report = row.security_report if isinstance(row.security_report, dict) else {}
    acknowledged = set(row.acknowledged_findings or [])
    blocked: dict[str, list[str]] = {"unacknowledged": [], "blocking": []}
    for finding in report.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        if finding.get("blocks"):
            blocked["blocking"].append(str(finding.get("id")))
        elif finding.get("severity") == HIGH and finding.get("acknowledge") and finding.get("id") not in acknowledged:
            blocked["unacknowledged"].append(str(finding.get("id")))
    return blocked


async def publish_checks(db: AsyncSession, skill: Skill, row: SkillVersion) -> None:
    conflicts = open_conflicts(row)
    if conflicts:
        raise SkillCatalogError("skill_draft_has_conflicts", conflicts=conflicts)
    spec = row.launch_spec if isinstance(row.launch_spec, dict) else {}
    if skill.kind == SKILL_KIND_MCP_SERVER and spec.get("image") and not spec.get("image_digest"):
        raise SkillCatalogError("skill_mcp_image_digest_missing",
                                message="Record the container image digest before publishing.")
    blocked = blocking_findings(row)
    if blocked["blocking"]:
        raise SkillCatalogError("skill_findings_blocking", findings=blocked["blocking"])
    if blocked["unacknowledged"]:
        raise SkillCatalogError("skill_findings_unacknowledged", findings=blocked["unacknowledged"])
    settings = await load_settings(db)
    if not settings.licence_allowed(row.licence_spdx):
        raise SkillCatalogError("skill_licence_not_allowed", licence=row.licence_spdx,
                                allowed=list(settings.licence_allowlist))


async def publish(db: AsyncSession, skill: Skill, row: SkillVersion, *, approval_id: str | None,
                  actor_id: str, self_approve: bool = False) -> PublishGate:
    if row.state != REVISION_STATE_IN_REVIEW:
        raise SkillCatalogError("skill_version_not_in_review", state=row.state)
    if self_approve and not approval_id:
        approval_id = await self_approve_review(db, row, actor_id=actor_id)
    gate = await check_publish_gate(db, row, approval_id)
    await publish_checks(db, skill, row)
    now = utc_now()
    previous = await published_version(db, skill)
    if previous is not None:
        previous.state, previous.retired_by, previous.retired_at = REVISION_STATE_RETIRED, actor_id, now
        previous.updated_at = now
        _audit(db, actor_id, AUDIT_RETIRED, skill, previous, replaced_by=row.version)
        await db.flush()
    row.state, row.approval_id, row.published_by = REVISION_STATE_PUBLISHED, gate.approval_id, actor_id
    row.published_at = row.updated_at = now
    if row.upstream_path:
        skill.upstream_path = row.upstream_path
    if skill.tracking_mode == TRACKING_PINNED and row.upstream_commit:
        skill.pinned_commit = row.upstream_commit  # "Update to …" moves the pin when the update is published
    status = skill.upstream_status if isinstance(skill.upstream_status, dict) else None
    if status and status.get("upstream_digest") == row.upstream_bundle_digest:
        skill.upstream_status = {**status, "update_available": False, "path_moved": None,
                                 "current_commit": row.upstream_commit}
    await db.flush()
    await sync_identity(db, skill, row)
    _audit(db, actor_id, AUDIT_PUBLISHED, skill, row, approval_id=gate.approval_id, approved_by=gate.approved_by,
           previous_version=previous.version if previous is not None else None, approval_mode=gate.approval_mode)
    await db.flush()
    return gate


async def retire(db: AsyncSession, skill: Skill, row: SkillVersion, *, actor_id: str) -> None:
    if row.state == REVISION_STATE_RETIRED:
        raise SkillCatalogError("skill_version_retired")
    was_published = row.state == REVISION_STATE_PUBLISHED
    now = utc_now()
    row.state, row.retired_by, row.retired_at, row.updated_at = REVISION_STATE_RETIRED, actor_id, now, now
    _audit(db, actor_id, AUDIT_RETIRED, skill, row, was_published=was_published)
    await db.flush()
    if was_published:
        await sync_identity(db, skill, None)
        await db.flush()


async def rollback(db: AsyncSession, skill: Skill, version: int, *, actor_id: str) -> SkillVersion:
    opened = await open_version(db, skill)
    if opened is not None:
        raise SkillCatalogError("skill_draft_exists", version=opened.version, state=opened.state)
    source = await get_version(db, skill, version)
    published = await published_version(db, skill)
    row = await draft_from(db, skill, source, actor_id=actor_id, note=f"Rollback to version {source.version}",
                           base_version=published.version if published else None)
    _audit(db, actor_id, AUDIT_DRAFT_SAVED, skill, row, created=True, rollback_of=source.version)
    return row


async def create_skill(db: AsyncSession, payload: dict[str, Any], *, actor_id: str) -> tuple[Skill, SkillVersion]:
    """A new skill written on the platform: identity + draft v1 (licence ``Internal``)."""
    name = str(payload.get("name") or "").strip()
    issue = name_issue(name)
    if issue is not None:
        raise SkillCatalogError("skill_spec_invalid", 422, issues=[issue.as_dict()])
    if (await db.execute(select(Skill.id).where(Skill.name == name))).first() is not None:
        raise SkillCatalogError("skill_name_exists", 409, name=name)
    frontmatter = dict(payload.get("frontmatter") or {})
    frontmatter["name"] = name
    skill = Skill(name=name, kind="skill", category="uncategorized", owner_id=actor_id, source="custom", tags=[])
    db.add(skill)
    await db.flush()
    await set_tags(db, skill, payload.get("tags") or [], actor_id=actor_id)
    row = await new_draft_row(db, skill, actor_id=actor_id, note=payload.get("note"), base_version=None)
    db.add(row)
    files = [BundleFile(SKILL_FILE, render_skill_md(frontmatter, str(payload.get("body") or "")))]
    files += [BundleFile(str(path), str(content)) for path, content in (payload.get("files") or {}).items()
              if path != SKILL_FILE and content is not None]
    await write_content(db, skill, row, VersionContent(
        files=files, extension=dict(payload.get("extension") or {}), category_id=payload.get("category_id"),
        available_platform_chat=bool(payload.get("available_platform_chat", True)),
        available_octryx_claude=bool(payload.get("available_octryx_claude", True)),
        licence_spdx=str(payload.get("licence_spdx") or LICENCE_INTERNAL)))
    skill.category_id = row.category_id
    skill.category = (await get_category(db, row.category_id)).key
    _audit(db, actor_id, AUDIT_DRAFT_SAVED, skill, row, created=True)
    await db.flush()
    return skill, row


__all__ = [
    "PublishGate",
    "blocking_findings",
    "check_publish_gate",
    "create_skill",
    "draft_from",
    "etag",
    "get_skill",
    "get_version",
    "list_versions",
    "open_conflicts",
    "open_version",
    "publish",
    "publish_checks",
    "published_version",
    "retire",
    "rollback",
    "save_draft",
    "start_draft",
    "submit",
]
