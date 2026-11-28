from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    CodeRepository,
    User,
    WorkItem,
    WorkItemChangeUnit,
    WorkRepositoryProfile,
)
from ...access_control import require_existing_workspace
from ...source_control.branch_naming import DEFAULT_BRANCH_RULE, render_branch
from ..config_visibility import refuse_userinfo, scope_filter, visible_rows
from ..jira_values import blank_to_none, list_value, object_value, optional_int, string_list
from ..plan_serializers import serialize_change_unit
from ..related_rows import REPOSITORY_PROFILE, load_optional_related
from ..serializers import serialize_repository_profile
from .redeclare import SUPERSEDED_UNIT_STATUS

PROFILE_REQUIRED_FIELDS = (
    "service_description",
    "owners",
    "default_reviewers",
    "default_branch",
    "build_commands",
    "test_commands",
    "lint_commands",
    "format_commands",
    "package_commands",
    "local_run_commands",
    "important_paths",
    "protected_paths",
    "artifact_paths",
    "test_report_paths",
)
COMMAND_PROFILE_FIELDS = (
    ("setup_commands", "setup_commands_json"),
    ("format_commands", "format_commands_json"),
    ("lint_commands", "lint_commands_json"),
    ("test_commands", "test_commands_json"),
    ("build_commands", "build_commands_json"),
    ("package_commands", "package_commands_json"),
    ("local_run_commands", "local_run_commands_json"),
    ("cleanup_commands", "cleanup_commands_json"),
)
VALIDATION_COMMAND_FIELDS = ("lint_commands_json", "test_commands_json", "build_commands_json", "package_commands_json")


async def list_repository_profiles(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    include_inactive: bool = False,
    project_scope: set[str] | None,
    viewer_id: str,
) -> list[dict[str, Any]]:
    stmt = select(WorkRepositoryProfile).where(scope_filter(WorkRepositoryProfile, project_scope, viewer_id))
    if project_id:
        stmt = stmt.where(WorkRepositoryProfile.project_id == project_id)
    if not include_inactive:
        stmt = stmt.where(WorkRepositoryProfile.is_active.is_(True))
    stmt = stmt.order_by(WorkRepositoryProfile.name.asc())
    return visible_rows(map(serialize_repository_profile, (await db.execute(stmt)).scalars()), project_scope)


async def plan_work_item_change_units(
    db: AsyncSession,
    *,
    work_item_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    item = await db.get(WorkItem, work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Work Item not found")
    raw_units = payload.get("units")
    if not isinstance(raw_units, list) or not raw_units:
        raise HTTPException(status_code=422, detail="units must contain at least one change unit")
    # Every unit (and the related rows it names) is resolved before anything is replaced.
    planned: list[WorkItemChangeUnit] = [
        await _change_unit_from_payload(
            db,
            current_user=current_user,
            item=item,
            payload=unit_payload,
            default_order=index,
        )
        for index, unit_payload in enumerate(raw_units)
        if isinstance(unit_payload, dict)
    ]
    if not planned:
        raise HTTPException(status_code=422, detail="No valid change units were provided")
    if bool(payload.get("replace_existing", True)):
        # Superseded units are audit trail from a redeclared work item; only
        # the active planning generation is replaced.
        existing = (
            await db.execute(
                select(WorkItemChangeUnit).where(
                    WorkItemChangeUnit.work_item_id == item.id,
                    WorkItemChangeUnit.status != SUPERSEDED_UNIT_STATUS,
                )
            )
        ).scalars()
        for row in existing:
            await db.delete(row)
        await db.flush()
    db.add_all(planned)
    await db.flush()
    return {"items": [serialize_change_unit(row) for row in planned]}


async def list_work_item_change_units(db: AsyncSession, work_item_id: str) -> list[dict[str, Any]]:
    stmt = (
        select(WorkItemChangeUnit)
        .where(WorkItemChangeUnit.work_item_id == work_item_id)
        .order_by(WorkItemChangeUnit.dependency_order.asc(), WorkItemChangeUnit.created_at.asc())
    )
    return [serialize_change_unit(row) for row in (await db.execute(stmt)).scalars().all()]


def suggest_branch_name(item: WorkItem, profile: WorkRepositoryProfile | None, override_rule: str | None = None) -> str:
    rule = override_rule or (profile.branch_naming_rule if profile else None) or DEFAULT_BRANCH_RULE
    jira_key = _safe_token(item.source_key).upper()
    slug = _safe_token(item.title).lower()
    branch = render_branch(rule, branch_type="feature", key=jira_key, slug=slug)
    return re.sub(r"[/_-]+$", "", branch[:240]) or f"feature/{jira_key.lower()}"


async def normalized_profile_payload(db: AsyncSession, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = blank_to_none(payload.get("project_id"))
    await require_existing_workspace(db, user_id, project_id)
    code_repository_id = blank_to_none(payload.get("code_repository_id"))
    code_repository = await _get_code_repository(db, code_repository_id)
    fallback_name = code_repository.name if code_repository else ""
    name = str(payload.get("name") or fallback_name).strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    return {
        "project_id": project_id,
        "code_repository_id": code_repository_id,
        "technology_baseline_id": None,
        "name": name[:220],
        "provider": str(
            payload.get("provider") or (code_repository.provider if code_repository else "bitbucket")
        ).strip()[:50],
        "repository_url": refuse_userinfo(blank_to_none(
            payload.get("repository_url") or (code_repository.remote_url if code_repository else None)
        ), "repository_url"),
        "default_branch": blank_to_none(
            payload.get("default_branch") or (code_repository.default_branch if code_repository else None)
        ),
        "protected_branches_json": string_list(payload.get("protected_branches")),
        "jira_project_keys_json": string_list(payload.get("jira_project_keys")),
        "service_description": blank_to_none(payload.get("service_description")),
        "owners_json": string_list(payload.get("owners")),
        "default_reviewers_json": string_list(payload.get("default_reviewers")),
        "branch_naming_rule": (str(payload.get("branch_naming_rule") or "").strip() or DEFAULT_BRANCH_RULE)[:220],
        "pr_target_branch": blank_to_none(payload.get("pr_target_branch") or payload.get("default_branch")),
        "required_pipelines_json": string_list(payload.get("required_pipelines")),
        "required_tests_json": string_list(payload.get("required_tests")),
        "setup_commands_json": _commands(payload, "setup_commands"),
        "build_commands_json": _commands(payload, "build_commands"),
        "test_commands_json": _commands(payload, "test_commands"),
        "lint_commands_json": _commands(payload, "lint_commands"),
        "format_commands_json": _commands(payload, "format_commands"),
        "package_commands_json": _commands(payload, "package_commands"),
        "local_run_commands_json": _commands(payload, "local_run_commands"),
        "cleanup_commands_json": _commands(payload, "cleanup_commands"),
        "builder_runtime_image": blank_to_none(payload.get("builder_runtime_image")),
        "local_toolchain_json": string_list(payload.get("local_toolchain")),
        "required_env_vars_json": string_list(payload.get("required_env_vars")),
        "secret_references_json": string_list(payload.get("secret_references")),
        "protected_paths_json": string_list(payload.get("protected_paths")),
        "hotspot_files_json": string_list(payload.get("hotspot_files")),
        "artifact_paths_json": string_list(payload.get("artifact_paths")),
        "coverage_report_paths_json": string_list(payload.get("coverage_report_paths")),
        "test_report_paths_json": string_list(payload.get("test_report_paths")),
        "multi_repo_dependencies_json": _object_list(payload.get("multi_repo_dependencies")),
        "risk_tags_json": string_list(payload.get("risk_tags")),
        "important_paths_json": string_list(payload.get("important_paths")),
        "profile_source": str(payload.get("profile_source") or "manual").strip()[:80],
        "review_status": str(payload.get("review_status") or "needs_review").strip()[:80],
        "is_active": bool(payload.get("is_active", True)),
    }


async def _get_code_repository(db: AsyncSession, code_repository_id: str | None) -> CodeRepository | None:
    if not code_repository_id:
        return None
    row = await db.get(CodeRepository, code_repository_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Code repository not found")
    return row


async def _change_unit_from_payload(
    db: AsyncSession,
    *,
    current_user: User,
    item: WorkItem,
    payload: dict[str, Any],
    default_order: int,
) -> WorkItemChangeUnit:
    profile = await load_optional_related(
        db, current_user, REPOSITORY_PROFILE, blank_to_none(payload.get("repository_profile_id")),
        for_workspace=item.project_id,
    )
    repository_name = str(payload.get("repository_name") or (profile.name if profile else "")).strip()
    if not repository_name:
        raise HTTPException(status_code=422, detail="repository_name is required when no profile is selected")
    expected_paths = string_list(payload.get("expected_paths") or (profile.important_paths_json if profile else []))
    validation_commands = string_list(payload.get("validation_commands")) or profile_validation_commands(profile)
    reviewer_policy = _reviewer_policy(payload, profile)
    branch_name = str(payload.get("branch_name") or suggest_branch_name(item, profile)).strip()
    dependency_order = _dependency_order(payload, default_order)
    return WorkItemChangeUnit(
        work_item_id=item.id,
        repository_profile_id=profile.id if profile else None,
        repository_name=repository_name[:220],
        branch_name=branch_name[:260],
        scope=str(payload.get("scope") or item.title or "").strip() or None,
        expected_paths_json=expected_paths,
        validation_commands_json=validation_commands,
        reviewer_policy_json=reviewer_policy,
        pr_link=blank_to_none(payload.get("pr_link")),
        dependency_order=str(dependency_order),
        status=str(payload.get("status") or "planned").strip()[:80],
        missing_profile_fields_json=_missing_profile_fields(profile),
        created_by=current_user.id,
        updated_by=current_user.id,
    )


def _reviewer_policy(payload: dict[str, Any], profile: WorkRepositoryProfile | None) -> dict[str, Any]:
    policy = object_value(payload.get("reviewer_policy"))
    if profile:
        policy.setdefault("owners", list(profile.owners_json or []))
        policy.setdefault("default_reviewers", list(profile.default_reviewers_json or []))
        policy.setdefault("target_branch", profile.pr_target_branch or profile.default_branch)
        policy.setdefault("protected_paths", list(profile.protected_paths_json or []))
        policy.setdefault("hotspot_files", list(profile.hotspot_files_json or []))
        policy.setdefault("command_profile", profile_command_profile(profile))
    policy.setdefault("required_reviewers", string_list(payload.get("reviewers")))
    return policy


def _dependency_order(payload: dict[str, Any], default_order: int) -> int:
    if payload.get("dependency_order") is None:
        return default_order
    return optional_int(payload.get("dependency_order")) or default_order


def profile_validation_commands(profile: WorkRepositoryProfile | None) -> list[str]:
    if not profile:
        return []
    commands: list[str] = []
    seen: set[str] = set()
    for field_name in VALIDATION_COMMAND_FIELDS:
        for command in getattr(profile, field_name) or []:
            text = str(command or "").strip()
            if text and text not in seen:
                seen.add(text)
                commands.append(text)
    return commands


def profile_command_profile(profile: WorkRepositoryProfile) -> dict[str, list[str]]:
    return {api_key: list(getattr(profile, model_key) or []) for api_key, model_key in COMMAND_PROFILE_FIELDS}


def _commands(payload: dict[str, Any], key: str) -> list[str]:
    return string_list(payload.get(key))


def _object_list(value: Any) -> list[dict[str, Any]]:
    return [dict(entry) for entry in list_value(value) if isinstance(entry, dict)]


def _missing_profile_fields(profile: WorkRepositoryProfile | None) -> list[str]:
    if profile is None:
        return list(PROFILE_REQUIRED_FIELDS)
    missing: list[str] = []
    if not profile.service_description:
        missing.append("service_description")
    if not profile.owners_json:
        missing.append("owners")
    if not profile.default_reviewers_json:
        missing.append("default_reviewers")
    if not profile.default_branch:
        missing.append("default_branch")
    if not profile.build_commands_json:
        missing.append("build_commands")
    if not profile.test_commands_json:
        missing.append("test_commands")
    if not profile.lint_commands_json:
        missing.append("lint_commands")
    if not profile.format_commands_json:
        missing.append("format_commands")
    if not profile.package_commands_json:
        missing.append("package_commands")
    if not profile.local_run_commands_json:
        missing.append("local_run_commands")
    if not profile.important_paths_json:
        missing.append("important_paths")
    if not profile.protected_paths_json:
        missing.append("protected_paths")
    if not profile.artifact_paths_json:
        missing.append("artifact_paths")
    if not profile.test_report_paths_json:
        missing.append("test_report_paths")
    return missing


def _safe_token(value: str | None) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip()).strip("-")
    return normalized[:64] or "work"
