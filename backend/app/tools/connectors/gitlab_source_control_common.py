"""Shared GitLab source-control helpers."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException

from ...services.git_http_auth import without_credentials
from ...services.project_resource_policy import RepositoryOperation, require_project_repository_operation
from ...services.source_control import (
    SourceControlOperation,
    SourceControlOperationResult,
    SourceControlProvider,
    SourceControlRepositoryRef,
    get_source_control_operation_contract,
    redact_source_control_text,
    sanitize_source_control_payload,
)
from ..context import ToolContext
from .common import _string
from .credential_boundary import connector_secret_value

GITLAB_CREDENTIAL_URL_RE = re.compile(r"\bhttps://[^@\s]+@[^/\s]+/[^\s]+", flags=re.IGNORECASE)


def gitlab_repository_ref(project: str) -> SourceControlRepositoryRef:
    return SourceControlRepositoryRef(provider=SourceControlProvider.GITLAB, repository=str(project or "").strip())


def gitlab_project_refs(project: str, *, configured_url: Any = None) -> list[str]:
    normalized = str(project or "").strip()
    return [normalized, normalized.rsplit("/", 1)[-1], gitlab_clone_url_for_project(normalized, configured_url=configured_url)]


async def require_gitlab_repository_operation(
    context: ToolContext,
    *,
    project: str,
    operation: RepositoryOperation,
) -> dict[str, Any] | None:
    try:
        await require_project_repository_operation(
            context.db,
            project_ids=context.project_ids,
            provider="gitlab",
            operation=operation,
            repository_refs=gitlab_project_refs(project, configured_url=context.project_config.get("gitlab_url")),
        )
    except HTTPException as exc:
        return {"error": exc.detail}
    return None


def gitlab_source_control_metadata(
    operation: SourceControlOperation,
    *,
    project: str,
    status: str,
    output: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = get_source_control_operation_contract(operation)
    repository = gitlab_repository_ref(project)
    safe_output = sanitize_source_control_payload(output or {})
    safe_evidence = sanitize_source_control_payload(evidence or {})
    result = SourceControlOperationResult(
        operation=operation,
        provider=SourceControlProvider.GITLAB,
        repository=repository,
        status=status,
        output=safe_output,
        evidence=safe_evidence,
    )
    return {
        "contract_version": "source_control.v1",
        "operation": result.operation.value,
        "provider": result.provider.value,
        "repository": repository.display_name,
        "repository_operation": contract.repository_operation,
        "repository_mode": contract.repository_mode.value,
        "mutation": contract.mutation.value,
        "policy_checks": [check.value for check in contract.required_policy_checks],
        "audit_fields": [field.value for field in contract.audit_fields],
        "status": result.status,
        "output": dict(result.output),
        "evidence": dict(result.evidence),
    }


def gitlab_clone_url_for_project(project: str, *, configured_url: Any = None) -> str:
    raw = _string(configured_url) or "https://gitlab.com"
    parsed = urlsplit(raw.rstrip("/"))
    path = parsed.path.rstrip("/")
    if path.endswith("/api/v4"):
        path = path[: -len("/api/v4")]
    elif path.endswith("/api"):
        path = path[: -len("/api")]
    return without_credentials(
        urlunsplit((parsed.scheme or "https", parsed.netloc or parsed.path, f"{path}/{project}.git", "", ""))
    )


def gitlab_clone_url(context: ToolContext, project: str) -> str:
    return gitlab_clone_url_for_project(project, configured_url=context.project_config.get("gitlab_url"))


def gitlab_git_auth_env(context: ToolContext) -> dict[str, str] | None:
    token = _string(context.project_config.get("gitlab_token"))
    if not token:
        return None
    return _gitlab_git_auth_env_for_token(token)


async def gitlab_git_auth_env_async(context: ToolContext) -> dict[str, str] | None:
    token = await connector_secret_value(context, connector_name="gitlab", field_name="gitlab_token")
    if not token:
        return None
    return _gitlab_git_auth_env_for_token(token)


def _gitlab_git_auth_env_for_token(token: str) -> dict[str, str]:
    from .askpass import askpass_script

    askpass_path = askpass_script("GITLAB", "oauth2")  # one script, no secret in it; never a folder per call
    env = dict(os.environ)
    env.update(
        {
            "GIT_ASKPASS": str(askpass_path),
            "GIT_TERMINAL_PROMPT": "0",
            "OCTRYX_GITLAB_USERNAME": "oauth2",
            "OCTRYX_GITLAB_SECRET": token,
        }
    )
    return env


def redact_gitlab_git_output(context: ToolContext, value: str) -> str:
    text = str(value or "")
    token = _string(context.project_config.get("gitlab_token"))
    if token:
        text = text.replace(token, "***")
    text = GITLAB_CREDENTIAL_URL_RE.sub("https://***/***", text)
    return redact_source_control_text(text)


__all__ = [
    "gitlab_clone_url",
    "gitlab_clone_url_for_project",
    "gitlab_git_auth_env",
    "gitlab_git_auth_env_async",
    "gitlab_project_refs",
    "gitlab_repository_ref",
    "gitlab_source_control_metadata",
    "redact_gitlab_git_output",
    "require_gitlab_repository_operation",
]
