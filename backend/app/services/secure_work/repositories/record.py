"""The repository record and its coding setup: read, list and save."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import CodeRepository, User, WorkRepositoryProfile
from ....models.project.knowledge_source_sync import KnowledgeSourceConnector
from ..config_visibility import unmasked, visible_rows
from ..plans.repository_planning import COMMAND_PROFILE_FIELDS, normalized_profile_payload
from ..serializers import serialize_repository_profile

SETUP_KEY = "coding_setup"
PROJECTION_SOURCE = "code_repository"
LIST_FIELDS = (
    "owners", "default_reviewers", "protected_branches", "required_pipelines", "required_tests",
    *(name for name, _column in COMMAND_PROFILE_FIELDS), "local_toolchain", "required_env_vars", "secret_references",
    "protected_paths", "hotspot_files", "artifact_paths", "coverage_report_paths", "test_report_paths", "risk_tags",
    "important_paths",
)
TEXT_FIELDS = ("service_description", "branch_naming_rule", "pr_target_branch", "builder_runtime_image")
OBJECT_LIST_FIELDS = ("multi_repo_dependencies",)
SETUP_FIELDS = (*TEXT_FIELDS, *LIST_FIELDS, *OBJECT_LIST_FIELDS)
SUMMARY_COMMANDS = (("build", "build_commands"), ("test", "test_commands"), ("lint", "lint_commands"))
# The declared test environment a run's runtimes prepare (setup, test, lint, path, check); stored on the record only.
ENVIRONMENT_KEY = "environment"
ENVIRONMENT_FILE_KEY = "environment_file"


def stored_setup(repo: CodeRepository) -> dict[str, Any]:
    stored = dict(repo.config_json or {}).get(SETUP_KEY)
    return dict(stored) if isinstance(stored, dict) else {}


def setup_summary(setup: dict[str, Any]) -> dict[str, list[str]]:
    configured = [label for label, key in SUMMARY_COMMANDS if setup.get(key)]
    return {"configured": configured, "missing": [label for label, _key in SUMMARY_COMMANDS if label not in configured]}


async def _sources(db: AsyncSession, repos: list[CodeRepository]) -> dict[str, str]:
    ids = {str((dict(repo.config_json or {}).get("central_source") or {}).get("connector_id") or "") for repo in repos}
    ids.discard("")
    if not ids:
        return {}
    rows = (await db.execute(select(KnowledgeSourceConnector).where(KnowledgeSourceConnector.id.in_(ids)))).scalars()
    return {row.id: row.connector_key for row in rows}


def _source_of(repo: CodeRepository, sources: dict[str, str]) -> dict[str, Any]:
    central = dict(repo.config_json or {}).get("central_source") or {}
    connector_id = str(central.get("connector_id") or "")
    if connector_id:
        return {"kind": "knowledge_source", "name": sources.get(connector_id, connector_id)}
    origin = str(dict(repo.config_json or {}).get("created_from") or "")
    return {"kind": origin or repo.provider, "name": repo.name}


def describe_repository(repo: CodeRepository, sources: dict[str, str]) -> dict[str, Any]:
    setup = stored_setup(repo)
    return {
        "id": repo.id,
        "project_id": repo.project_id,
        "name": repo.name,
        "provider": repo.provider,
        "default_branch": repo.default_branch,
        "source": _source_of(repo, sources),
        "owners": list(setup.get("owners") or []),
        "coding_setup": setup_summary(setup),
        "operation_policy": dict(dict(repo.config_json or {}).get("operation_policy") or {}),
        "last_index_status": repo.last_index_status,
        "last_indexed_at": repo.last_indexed_at.isoformat() if repo.last_indexed_at else None,
    }


async def workspace_repositories(db: AsyncSession, project_id: str) -> list[dict[str, Any]]:
    repos = list((await db.execute(
        select(CodeRepository).where(CodeRepository.project_id == project_id, CodeRepository.is_active.is_(True))
        .order_by(CodeRepository.name)
    )).scalars())
    sources = await _sources(db, repos)
    branches = await _source_branches(db, project_id, repos)
    rows = []
    for repo in repos:
        row = describe_repository(repo, sources)
        if not row["default_branch"] and branches.get(repo.id):
            row["default_branch"], row["default_branch_from"] = branches[repo.id], "knowledge_source"
        rows.append(row)
    return rows


async def _source_branches(db: AsyncSession, project_id: str, repos: list[CodeRepository]) -> dict[str, str]:
    from ...workflow_runs.platform.repo_ref import record_path

    missing = [repo for repo in repos if not repo.default_branch]
    if not missing:
        return {}
    connectors = list((await db.execute(select(KnowledgeSourceConnector).where(
        KnowledgeSourceConnector.project_id == project_id))).scalars())
    by_id = {row.id: row for row in connectors}

    def ref_of(row: KnowledgeSourceConnector | None) -> str:
        scope = row.scope if row is not None and isinstance(row.scope, dict) else {}
        return str(scope.get("ref") or "").strip()

    def remote_of(row: KnowledgeSourceConnector) -> str:
        scope = row.scope if isinstance(row.scope, dict) else {}
        return str(scope.get("remote") or "").strip().rstrip("/").lower().removesuffix(".git")

    found: dict[str, str] = {}
    for repo in missing:
        own = by_id.get(str((dict(repo.config_json or {}).get("central_source") or {}).get("connector_id") or ""))
        path = record_path(repo.name)
        match = own or next((row for row in connectors if ref_of(row) and (
            remote_of(row).endswith("/" + path) or remote_of(row).endswith("/repos/" + path.split("/")[-1])
            and f"/projects/{path.split('/')[0]}/" in remote_of(row))), None)
        if ref_of(match):
            found[repo.id] = ref_of(match)
    return found


async def workspace_repository(db: AsyncSession, project_id: str, repository_id: str) -> CodeRepository:
    repo = await db.get(CodeRepository, repository_id)
    if repo is None or repo.project_id != project_id or not repo.is_active:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


async def projection_of(db: AsyncSession, repo: CodeRepository) -> WorkRepositoryProfile | None:
    return (await db.execute(
        select(WorkRepositoryProfile).where(WorkRepositoryProfile.code_repository_id == repo.id)
        .order_by(WorkRepositoryProfile.created_at).limit(1)
    )).scalar_one_or_none()


def _setup_from_normalized(normalized: dict[str, Any]) -> dict[str, Any]:
    setup: dict[str, Any] = {}
    for key in SETUP_FIELDS:
        column = key if key in TEXT_FIELDS else f"{key}_json"
        value = normalized.get(column)
        if value not in (None, "", []):
            setup[key] = value
    return setup


async def read_setup(db: AsyncSession, repo: CodeRepository, *, scope: set[str] | None) -> dict[str, Any]:
    # Secret references stay masked unless the reader is a platform admin.
    setup = stored_setup(repo)
    shown = {key: setup.get(key, [] if key in (*LIST_FIELDS, *OBJECT_LIST_FIELDS) else "") for key in SETUP_FIELDS}
    shown[ENVIRONMENT_KEY] = setup.get(ENVIRONMENT_KEY)
    shown[ENVIRONMENT_FILE_KEY] = setup.get(ENVIRONMENT_FILE_KEY)
    (masked,) = visible_rows([{**shown, "project_id": repo.project_id}], scope)
    masked.pop("project_id", None)
    masked.pop("read_only", None)
    return {"repository_id": repo.id, "coding_setup": masked, "summary": setup_summary(setup)}


def _environment(payload: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any] | None:
    from ...workflow_runs.workspace.spec import validate_environment

    if ENVIRONMENT_KEY not in payload:
        return previous.get(ENVIRONMENT_KEY) if isinstance(previous.get(ENVIRONMENT_KEY), dict) else None
    environment, errors = validate_environment(payload[ENVIRONMENT_KEY])
    if errors:
        raise HTTPException(status_code=422, detail={"code": "invalid_environment", "errors": errors})
    return environment


def _environment_file(payload: dict[str, Any], previous: dict[str, Any]) -> str | None:
    from ...workflow_runs.workspace.spec import validate_environment_file

    if ENVIRONMENT_FILE_KEY not in payload:
        kept = previous.get(ENVIRONMENT_FILE_KEY)
        return kept if isinstance(kept, str) and kept else None
    path, errors = validate_environment_file(payload[ENVIRONMENT_FILE_KEY])
    if errors:
        raise HTTPException(status_code=422, detail={"code": "invalid_environment_file", "errors": errors})
    return path


async def save_setup(db: AsyncSession, *, user: User, repo: CodeRepository, payload: dict[str, Any]) -> dict[str, Any]:
    previous = stored_setup(repo)
    projection = await projection_of(db, repo)
    incoming = unmasked({key: payload[key] for key in SETUP_FIELDS if key in payload}, previous)
    merged = {**previous, **incoming}
    normalized = await normalized_profile_payload(db, user.id, {
        **merged, "project_id": repo.project_id, "code_repository_id": repo.id, "name": repo.name,
        "provider": repo.provider, "repository_url": repo.remote_url, "default_branch": repo.default_branch,
        "profile_source": PROJECTION_SOURCE, "review_status": "reviewed",
    })
    stored = _setup_from_normalized(normalized)
    environment = _environment(payload, previous)
    environment_file = _environment_file(payload, previous)
    if environment_file:
        stored[ENVIRONMENT_FILE_KEY] = environment_file
    if environment:
        stored[ENVIRONMENT_KEY] = environment
    repo.config_json = {**dict(repo.config_json or {}), SETUP_KEY: stored}
    if projection is None:
        projection = WorkRepositoryProfile(created_by=user.id)
        db.add(projection)
    for key, value in normalized.items():
        setattr(projection, key, value)
    projection.jira_project_keys_json = []  # the link runs through work items
    projection.technology_baseline_id = None  # repository projections carry no technology baseline
    projection.updated_by = user.id
    await db.flush()
    return {"repository_id": repo.id, "coding_setup": stored_setup(repo), "summary": setup_summary(stored_setup(repo)),
            "runtime_profile": serialize_repository_profile(projection)}


__all__ = [
    "PROJECTION_SOURCE",
    "SETUP_FIELDS",
    "SETUP_KEY",
    "describe_repository",
    "projection_of",
    "read_setup",
    "save_setup",
    "setup_summary",
    "stored_setup",
    "workspace_repositories",
    "workspace_repository",
]
