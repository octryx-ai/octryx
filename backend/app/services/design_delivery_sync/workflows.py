"""Workflow configuration helpers for design delivery sync."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DesignTraceSyncTemplate, Project

TRACE_SYNC_TEMPLATE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "releases",
        "name": "Release Sync",
        "description": "Import matching releases and tags from connected repositories.",
        "source_kind": "release",
        "target_type": "release",
        "mode": "auto_link",
        "is_active": True,
        "providers": ["github", "bitbucket"],
        "match_rules": ["artifact_tokens", "task_titles", "linked_pull_requests"],
        "limit_per_repository": 30,
    },
    {
        "id": "checkpoints",
        "name": "Checkpoint Sync",
        "description": "Import matching workflow or pipeline checkpoints from connected repositories.",
        "source_kind": "checkpoint",
        "target_type": "checkpoint",
        "mode": "auto_link",
        "is_active": True,
        "providers": ["github", "bitbucket"],
        "match_rules": ["artifact_tokens", "linked_pull_requests", "linked_releases"],
        "limit_per_repository": 30,
    },
)

WORKFLOW_IDS = {str(item["id"]) for item in TRACE_SYNC_TEMPLATE_DEFINITIONS}
# Pull requests are not synced into design traceability (cut from the alpha); a trace link to a pull request is
# still made by hand (``design_artifact``) and read by the ``linked_pull_requests`` rule.
SOURCE_KINDS = TARGET_TYPES = {"release", "checkpoint"}
ALLOWED_PROVIDERS = {"github", "bitbucket", "gitlab"}
MATCH_RULE_ALIASES = {
    "artifact_tokens": "artifact_tokens",
    "artifact_titles": "artifact_titles",
    "artifact_title": "artifact_titles",
    "artifact_summaries": "artifact_summaries",
    "artifact_summary": "artifact_summaries",
    "task_titles": "task_titles",
    "linked_pull_requests": "linked_pull_requests",
    "linked_pull_request": "linked_pull_requests",
    "linked_releases": "linked_releases",
    "linked_release": "linked_releases",
}
SYNC_MODES = {"auto_link", "suggest"}
CUSTOM_WORKFLOW_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")


def list_design_trace_sync_templates() -> list[dict[str, Any]]:
    return [dict(item) for item in TRACE_SYNC_TEMPLATE_DEFINITIONS]


def normalize_match_rules(raw_rules: Any, fallback_rules: list[str]) -> list[str]:
    normalized: list[str] = []
    source = raw_rules if isinstance(raw_rules, list) else fallback_rules
    for value in source or []:
        key = MATCH_RULE_ALIASES.get(str(value).strip().lower())
        if key and key not in normalized:
            normalized.append(key)
    return normalized or list(fallback_rules)


def _serialize_custom_template_row(row: DesignTraceSyncTemplate) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": str(row.name or row.id),
        "description": str(row.description or ""),
        "source_kind": str(row.source_kind),
        "target_type": str(row.target_type),
        "mode": str(row.mode or "auto_link"),
        "is_active": bool(row.is_active),
        "providers": [provider for provider in row.providers if provider in ALLOWED_PROVIDERS],
        "match_rules": normalize_match_rules(row.match_rules, ["artifact_tokens", "task_titles"]),
        "limit_per_repository": max(1, min(int(str(row.limit_per_repository or "30") or "30"), 100)),
        "template_id": "",
        "is_template": False,
        "project_id": str(row.project_id or ""),
    }


async def list_project_design_trace_sync_templates(db: AsyncSession, *, project_id: str) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(DesignTraceSyncTemplate)
                .where(DesignTraceSyncTemplate.project_id == project_id)
                .order_by(DesignTraceSyncTemplate.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_serialize_custom_template_row(row) for row in rows]


async def upsert_project_design_trace_sync_template(
    db: AsyncSession,
    *,
    project_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    template_id = str(payload.get("id") or "").strip()
    if not template_id or not CUSTOM_WORKFLOW_ID_RE.match(template_id) or template_id in WORKFLOW_IDS:
        raise ValueError("Invalid custom workflow template id")
    source_kind = str(payload.get("source_kind") or "").strip().lower()
    target_type = str(payload.get("target_type") or source_kind).strip().lower()
    if source_kind not in SOURCE_KINDS or target_type not in TARGET_TYPES:
        kinds = ", ".join(sorted(SOURCE_KINDS))
        raise ValueError(f"Unsupported trace sync source kind or target type (one of: {kinds})")
    row = (
        await db.execute(
            select(DesignTraceSyncTemplate).where(
                DesignTraceSyncTemplate.project_id == project_id,
                DesignTraceSyncTemplate.id == template_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = DesignTraceSyncTemplate(id=template_id, project_id=project_id)
        db.add(row)
    row.name = str(payload.get("name") or template_id).strip() or template_id
    row.description = str(payload.get("description") or "").strip()
    row.source_kind, row.target_type = source_kind, target_type
    row.mode = str(payload.get("mode") or "auto_link").strip().lower()
    row.is_active = bool(payload.get("is_active", True))
    row.providers = [
        provider
        for provider in [str(value).strip().lower() for value in (payload.get("providers") or [])]
        if provider in ALLOWED_PROVIDERS
    ] or ["github", "bitbucket"]
    row.match_rules = normalize_match_rules(payload.get("match_rules"), ["artifact_tokens", "task_titles"])
    row.limit_per_repository = str(max(1, min(int(payload.get("limit_per_repository") or 30), 100)))
    await db.commit()
    await db.refresh(row)
    return _serialize_custom_template_row(row)


async def delete_project_design_trace_sync_template(
    db: AsyncSession, *, project_id: str, template_id: str
) -> dict[str, Any]:
    row = (
        await db.execute(
            select(DesignTraceSyncTemplate).where(
                DesignTraceSyncTemplate.project_id == project_id,
                DesignTraceSyncTemplate.id == template_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError("Trace sync template not found")
    await db.delete(row)
    await db.commit()
    return {"status": "deleted", "id": template_id, "project_id": project_id}


def _normalize_trace_sync_workflow(raw: Any, template: dict[str, Any], *, is_template: bool) -> dict[str, Any]:
    item = dict(raw or {}) if isinstance(raw, dict) else {}
    providers = [
        str(value).strip().lower()
        for value in (
            item.get("providers") if isinstance(item.get("providers"), list) else template.get("providers") or []
        )
        if str(value).strip().lower() in ALLOWED_PROVIDERS
    ]
    match_rules = normalize_match_rules(item.get("match_rules"), list(template.get("match_rules") or []))
    mode = str(item.get("mode") or template.get("mode") or "auto_link").strip().lower()
    if mode not in SYNC_MODES:
        mode = "auto_link"
    source_kind = str(item.get("source_kind") or template.get("source_kind") or "").strip().lower()
    if source_kind not in SOURCE_KINDS:
        source_kind = str(template["source_kind"])
    target_type = str(item.get("target_type") or template.get("target_type") or "").strip().lower()
    if target_type not in TARGET_TYPES:
        target_type = str(template["target_type"])
    try:
        limit_per_repository = int(item.get("limit_per_repository") or template.get("limit_per_repository") or 30)
    except (TypeError, ValueError):
        limit_per_repository = 30
    limit_per_repository = max(1, min(limit_per_repository, 100))
    return {
        "id": str(item.get("id") or template["id"]).strip(),
        "name": str(item.get("name") or template.get("name") or item.get("id") or template["id"]).strip(),
        "description": str(item.get("description") or template.get("description") or "").strip(),
        "source_kind": source_kind,
        "target_type": target_type,
        "mode": mode,
        "is_active": bool(item.get("is_active", template.get("is_active", True))),
        "providers": providers or list(template.get("providers") or []),
        "match_rules": match_rules,
        "limit_per_repository": limit_per_repository,
        "template_id": str(template["id"]) if is_template else str(template.get("template_id") or ""),
        "is_template": is_template,
    }


def normalize_design_trace_sync_workflows(raw: Any) -> list[dict[str, Any]]:
    raw_by_id = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "").strip()
            if item_id:
                raw_by_id[item_id] = item
    normalized = []
    for template in TRACE_SYNC_TEMPLATE_DEFINITIONS:
        normalized.append(
            _normalize_trace_sync_workflow(raw_by_id.get(str(template["id"])), template, is_template=True)
        )
    for item_id, item in raw_by_id.items():
        if item_id in WORKFLOW_IDS or not CUSTOM_WORKFLOW_ID_RE.match(item_id):
            continue
        source_kind = str(item.get("source_kind") or "").strip().lower()
        target_type = str(item.get("target_type") or "").strip().lower()
        if source_kind not in SOURCE_KINDS or target_type not in TARGET_TYPES:
            continue
        synthetic_template = {
            "id": item_id,
            "name": str(item.get("name") or item_id).strip(),
            "description": str(item.get("description") or "").strip(),
            "source_kind": source_kind,
            "target_type": target_type,
            "mode": "auto_link",
            "is_active": True,
            "providers": ["github", "bitbucket"],
            "match_rules": ["artifact_tokens", "task_titles"],
            "limit_per_repository": 30,
            "template_id": "",
        }
        normalized.append(_normalize_trace_sync_workflow(item, synthetic_template, is_template=False))
    return normalized


def get_project_design_trace_sync_workflows(
    project_config: dict[str, Any] | None,
    *,
    custom_templates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    config = dict(project_config or {})
    normalized = normalize_design_trace_sync_workflows(config.get("design_trace_sync_workflows"))
    for item in custom_templates or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        normalized = [existing for existing in normalized if str(existing.get("id") or "") != item_id]
        normalized.append(item)
    return normalized


async def update_project_design_trace_sync_workflows(
    db: AsyncSession,
    *,
    project_id: str,
    workflows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise ValueError("Project not found")
    config = dict(project.config or {}) if isinstance(project.config, dict) else {}
    normalized = normalize_design_trace_sync_workflows(workflows)
    config["design_trace_sync_workflows"] = normalized
    project.config = config
    await db.commit()
    await db.refresh(project)
    return get_project_design_trace_sync_workflows(config)
