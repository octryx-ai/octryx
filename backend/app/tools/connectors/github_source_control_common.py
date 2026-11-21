"""Shared GitHub source-control helpers."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException

from ...services.git_http_auth import without_credentials
from ...services.github_url import normalize_github_api_base_url
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
from .credential_boundary import connector_secret_value

GITHUB_CREDENTIAL_URL_RE = re.compile(r"\bhttps://[^@\s]+@github\.com/[^\s]+", flags=re.IGNORECASE)


def github_repository_ref(owner: str, repo: str) -> SourceControlRepositoryRef:
    return SourceControlRepositoryRef(
        provider=SourceControlProvider.GITHUB,
        owner=str(owner or "").strip(),
        repository=str(repo or "").strip(),
    )


def github_repository_refs(owner: str, repo: str) -> list[str]:
    normalized_owner = str(owner or "").strip()
    normalized_repo = str(repo or "").strip()
    return [
        normalized_repo,
        f"{normalized_owner}/{normalized_repo}",
        github_clone_url_for_repository(normalized_owner, normalized_repo),
    ]


async def require_github_repository_operation(
    context: ToolContext,
    *,
    owner: str,
    repo: str,
    operation: RepositoryOperation,
) -> dict[str, Any] | None:
    try:
        await require_project_repository_operation(
            context.db,
            project_ids=context.project_ids,
            provider="github",
            operation=operation,
            repository_refs=github_repository_refs(owner, repo),
        )
    except HTTPException as exc:
        return {"error": exc.detail}
    return None


def github_source_control_metadata(
    operation: SourceControlOperation,
    *,
    owner: str,
    repo: str,
    status: str,
    output: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = get_source_control_operation_contract(operation)
    repository = github_repository_ref(owner, repo)
    safe_output = sanitize_source_control_payload(output or {})
    safe_evidence = sanitize_source_control_payload(evidence or {})
    result = SourceControlOperationResult(
        operation=operation,
        provider=SourceControlProvider.GITHUB,
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


def github_clone_url_for_repository(owner: str, repo: str, *, configured_url: Any = None) -> str:
    api_base = normalize_github_api_base_url(configured_url)
    parsed = urlsplit(api_base)
    if parsed.netloc == "api.github.com":
        return f"https://github.com/{owner}/{repo}.git"
    path = parsed.path.rstrip("/")
    if path.endswith("/api/v3"):
        path = path[: -len("/api/v3")]
    elif path.endswith("/api"):
        path = path[: -len("/api")]
    return without_credentials(urlunsplit((parsed.scheme or "https", parsed.netloc, f"{path}/{owner}/{repo}.git", "", "")))


def github_clone_url(context: ToolContext, owner: str, repo: str) -> str:
    configured = (
        context.project_config.get("github_clone_base_url")
        or context.project_config.get("github_web_url")
        or context.project_config.get("github_url")
    )
    return github_clone_url_for_repository(owner, repo, configured_url=configured)


def github_git_auth_env(context: ToolContext) -> dict[str, str] | None:
    token = str(context.project_config.get("github_token") or "").strip()
    if not token:
        return None
    return _github_git_auth_env_for_token(token)


async def github_git_auth_env_async(context: ToolContext) -> dict[str, str] | None:
    token = await connector_secret_value(context, connector_name="github", field_name="github_token")
    if not token:
        return None
    return _github_git_auth_env_for_token(token)


def _github_git_auth_env_for_token(token: str) -> dict[str, str]:
    from .askpass import askpass_script

    askpass_path = askpass_script("GITHUB", "x-access-token")  # one script, no secret in it; never a folder per call
    env = dict(os.environ)
    env.update(
        {
            "GIT_ASKPASS": str(askpass_path),
            "GIT_TERMINAL_PROMPT": "0",
            "OCTRYX_GITHUB_USERNAME": "x-access-token",
            "OCTRYX_GITHUB_SECRET": token,
        }
    )
    return env


def redact_github_git_output(context: ToolContext, value: str) -> str:
    text = str(value or "")
    token = str(context.project_config.get("github_token") or "").strip()
    if token:
        text = text.replace(token, "***")
    text = GITHUB_CREDENTIAL_URL_RE.sub("https://github.com/***", text)
    return redact_source_control_text(text)


__all__ = [
    "github_clone_url",
    "github_clone_url_for_repository",
    "github_git_auth_env",
    "github_git_auth_env_async",
    "github_repository_ref",
    "github_repository_refs",
    "github_source_control_metadata",
    "redact_github_git_output",
    "require_github_repository_operation",
]
