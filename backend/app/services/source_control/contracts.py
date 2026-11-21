"""Provider-neutral source-control operation contracts.

This module is intentionally secret-free. Provider implementations may hold
credentials behind their connector boundary, but runtime/tool/model/audit
payloads should only carry normalized operation contracts and safe evidence.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..project_resource_policy import RepositoryOperation


class SourceControlContractError(ValueError):
    """Raised when a source-control contract payload carries unsafe material."""


class SourceControlProvider(StrEnum):
    BITBUCKET = "bitbucket"
    GITHUB = "github"
    GITLAB = "gitlab"


class SourceControlOperation(StrEnum):
    LIST_REPOSITORIES = "list_repositories"
    READ_FILE = "read_file"
    LIST_BRANCHES = "list_branches"
    CREATE_BRANCH = "create_branch"
    PREPARE_REPOSITORY = "prepare_repository"
    COMMIT = "commit"
    PUSH = "push"
    CREATE_CHANGE_REQUEST = "create_change_request"
    GET_CHANGE_REQUEST = "get_change_request"
    UPDATE_CHANGE_REQUEST = "update_change_request"
    LIST_CHANGE_REQUESTS = "list_change_requests"
    LIST_PIPELINES = "list_pipelines"


class SourceControlRepositoryMode(StrEnum):
    READONLY = "readonly"
    BRANCH = "branch"
    WRITE = "write"
    DELIVERY = "delivery"


class SourceControlPolicyCheck(StrEnum):
    CONNECTOR_ACTIVE = "connector_active"
    TOOL_VISIBLE = "tool_visible"
    CONNECTOR_ALLOWLIST = "connector_allowlist"
    REPOSITORY_CONFIGURED = "repository_configured"
    REPOSITORY_OPERATION_POLICY = "repository_operation_policy"
    SECRET_SCOPE_BOUND = "secret_scope_bound"
    WORKSPACE_BOUNDARY = "workspace_boundary"
    APPROVAL_POLICY = "approval_policy"
    EVIDENCE_REDACTION = "evidence_redaction"


class SourceControlMutation(StrEnum):
    NONE = "none"
    WORKSPACE = "workspace"
    REMOTE = "remote"
    WORKSPACE_AND_REMOTE = "workspace_and_remote"


class SourceControlAuditField(StrEnum):
    OPERATION = "operation"
    PROVIDER = "provider"
    PROJECT_IDS = "project_ids"
    REPOSITORY = "repository"
    ACTOR_ID = "actor_id"
    SESSION_ID = "session_id"
    REQUEST_ID = "request_id"
    POLICY_DECISION = "policy_decision"
    APPROVAL_ID = "approval_id"
    RESULT_STATUS = "result_status"
    SAFE_EVIDENCE = "safe_evidence"


FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "api_key",
        "args",
        "argv",
        "auth",
        "authenticated_clone_url",
        "authorization",
        "cmd",
        "command",
        "credential",
        "credentials",
        "env",
        "environment",
        "header",
        "headers",
        "password",
        "private_key",
        "raw_command",
        "secret",
        "shell",
        "ssh_key",
        "token",
    }
)
FORBIDDEN_PAYLOAD_SUFFIXES = (
    "_api_key",
    "_credential",
    "_credentials",
    "_password",
    "_private_key",
    "_secret",
    "_ssh_key",
    "_token",
)
SAFE_URL_SCHEMES = {"http", "https", "ssh", "git"}
URL_IN_TEXT_RE = re.compile(r"\b(?:https?|ssh|git)://[^\s<>()]+")
SOURCE_CONTROL_REDACTED_VALUE = "[redacted]"
SOURCE_CONTROL_TEXT_LIMIT = 4000
AUTH_HEADER_RE = re.compile(r"\b(authorization)(\s*[:=]\s*)(?:bearer|basic)\s+[^\s,;]+", re.IGNORECASE)
AUTH_TOKEN_RE = re.compile(r"\b(bearer|basic)\s+[a-z0-9._~+/=-]+", re.IGNORECASE)
SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(authorization|api[_-]?key|password|token|secret|credential)(\s*[:=]\s*)([^\s,;]+)",
    re.IGNORECASE,
)


def _is_forbidden_payload_key(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    return normalized in FORBIDDEN_PAYLOAD_KEYS or normalized.endswith(FORBIDDEN_PAYLOAD_SUFFIXES)


def _redact_url_credentials(raw_url: str) -> str:
    candidate = str(raw_url or "")
    trailing = ""
    while candidate and candidate[-1] in ".,;":
        trailing = candidate[-1] + trailing
        candidate = candidate[:-1]
    parsed = urlsplit(candidate)
    if parsed.scheme in SAFE_URL_SCHEMES and (parsed.username or parsed.password):
        hostname = parsed.hostname or ""
        netloc = f"{hostname}:{parsed.port}" if parsed.port else hostname
        candidate = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    return candidate + trailing


def redact_source_control_text(value: Any, *, max_length: int = SOURCE_CONTROL_TEXT_LIMIT) -> str:
    """Return a bounded source-control evidence string without credential material."""

    text = str(value or "")
    text = URL_IN_TEXT_RE.sub(lambda match: _redact_url_credentials(match.group(0)), text)
    text = AUTH_HEADER_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}{SOURCE_CONTROL_REDACTED_VALUE}", text)
    text = AUTH_TOKEN_RE.sub(lambda match: f"{match.group(1)} {SOURCE_CONTROL_REDACTED_VALUE}", text)
    text = SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{SOURCE_CONTROL_REDACTED_VALUE}",
        text,
    )
    if len(text) > max_length:
        return text[:max_length] + "...[truncated]"
    return text


def sanitize_source_control_payload(value: Any) -> Any:
    """Recursively sanitize provider output/evidence before serialization."""

    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        redacted_fields: set[str] = set()
        for key, nested in value.items():
            key_text = str(key)
            if _is_forbidden_payload_key(key_text):
                redacted_fields.add(key_text)
                continue
            sanitized[key_text] = sanitize_source_control_payload(nested)
        if redacted_fields:
            existing = sanitized.get("redacted_fields")
            if isinstance(existing, list):
                redacted_fields.update(str(field) for field in existing)
            sanitized["redacted_fields"] = sorted(redacted_fields)
        return sanitized
    if isinstance(value, (list, tuple, set)):
        return [sanitize_source_control_payload(nested) for nested in value]
    if isinstance(value, str):
        return redact_source_control_text(value)
    return value


def _assert_safe_key(key: str, *, path: str) -> None:
    normalized = str(key or "").strip().lower()
    if not normalized:
        raise SourceControlContractError(f"{path} must not be empty")
    if _is_forbidden_payload_key(normalized):
        raise SourceControlContractError(f"{path} '{key}' is not allowed in source-control contracts")


def _assert_safe_payload(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_path = f"{path}.{key}"
            _assert_safe_key(str(key), path=key_path)
            _assert_safe_payload(nested, path=key_path)
        return
    if isinstance(value, (list, tuple, set)):
        for index, nested in enumerate(value):
            _assert_safe_payload(nested, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        _assert_safe_string(value, path=path)


def _assert_safe_string(value: str, *, path: str) -> None:
    text = value.strip()
    if not text:
        return
    candidates = [text, *URL_IN_TEXT_RE.findall(text)]
    for candidate in candidates:
        parsed = urlsplit(candidate.rstrip(".,;"))
        if parsed.scheme in SAFE_URL_SCHEMES and (parsed.username or parsed.password):
            raise SourceControlContractError(f"{path} must not contain credentialed URLs")


@dataclass(frozen=True)
class SourceControlField:
    name: str
    description: str
    required: bool = True

    def __post_init__(self) -> None:
        _assert_safe_key(self.name, path="field.name")


@dataclass(frozen=True)
class SourceControlOperationContract:
    operation: SourceControlOperation
    repository_operation: RepositoryOperation | None
    repository_mode: SourceControlRepositoryMode
    mutation: SourceControlMutation
    required_policy_checks: tuple[SourceControlPolicyCheck, ...]
    input_fields: tuple[SourceControlField, ...]
    output_fields: tuple[SourceControlField, ...]
    audit_fields: tuple[SourceControlAuditField, ...]
    description: str

    @property
    def mutates_remote(self) -> bool:
        return self.mutation in {SourceControlMutation.REMOTE, SourceControlMutation.WORKSPACE_AND_REMOTE}

    @property
    def mutates_workspace(self) -> bool:
        return self.mutation in {SourceControlMutation.WORKSPACE, SourceControlMutation.WORKSPACE_AND_REMOTE}


@dataclass(frozen=True)
class SourceControlRepositoryRef:
    provider: SourceControlProvider | str
    repository: str
    project_key: str | None = None
    owner: str | None = None
    remote_url: str | None = None
    web_url: str | None = None
    default_branch: str | None = None

    def __post_init__(self) -> None:
        provider = SourceControlProvider(str(self.provider).strip().lower())
        repository = str(self.repository or "").strip()
        if not repository:
            raise SourceControlContractError("repository is required")
        _assert_safe_payload(
            {
                "provider": provider.value,
                "repository": repository,
                "project_key": self.project_key,
                "owner": self.owner,
                "remote_url": self.remote_url,
                "web_url": self.web_url,
                "default_branch": self.default_branch,
            },
            path="repository",
        )
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "repository", repository)

    @property
    def display_name(self) -> str:
        if self.project_key:
            return f"{self.project_key}/{self.repository}"
        if self.owner:
            return f"{self.owner}/{self.repository}"
        return self.repository


@dataclass(frozen=True)
class SourceControlOperationRequest:
    operation: SourceControlOperation | str
    provider: SourceControlProvider | str
    project_ids: tuple[str, ...]
    repository: SourceControlRepositoryRef | None = None
    actor_id: str | None = None
    session_id: str | None = None
    request_id: str | None = None
    inputs: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        operation = SourceControlOperation(str(self.operation).strip().lower())
        provider = SourceControlProvider(str(self.provider).strip().lower())
        project_ids = tuple(str(project_id).strip() for project_id in self.project_ids if str(project_id).strip())
        _assert_safe_payload(
            {
                "actor_id": self.actor_id,
                "session_id": self.session_id,
                "request_id": self.request_id,
                "inputs": dict(self.inputs),
            },
            path="request",
        )
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "project_ids", project_ids)


@dataclass(frozen=True)
class SourceControlOperationResult:
    operation: SourceControlOperation | str
    provider: SourceControlProvider | str
    status: str
    repository: SourceControlRepositoryRef | None = None
    output: Mapping[str, Any] = field(default_factory=dict)
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        operation = SourceControlOperation(str(self.operation).strip().lower())
        provider = SourceControlProvider(str(self.provider).strip().lower())
        status = str(self.status or "").strip().lower()
        if not status:
            raise SourceControlContractError("status is required")
        _assert_safe_payload({"output": dict(self.output), "evidence": dict(self.evidence)}, path="result")
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "status", status)


BASE_AUDIT_FIELDS = (
    SourceControlAuditField.OPERATION,
    SourceControlAuditField.PROVIDER,
    SourceControlAuditField.PROJECT_IDS,
    SourceControlAuditField.REPOSITORY,
    SourceControlAuditField.ACTOR_ID,
    SourceControlAuditField.SESSION_ID,
    SourceControlAuditField.REQUEST_ID,
    SourceControlAuditField.POLICY_DECISION,
    SourceControlAuditField.RESULT_STATUS,
    SourceControlAuditField.SAFE_EVIDENCE,
)
BASE_POLICY_CHECKS = (
    SourceControlPolicyCheck.CONNECTOR_ACTIVE,
    SourceControlPolicyCheck.TOOL_VISIBLE,
    SourceControlPolicyCheck.CONNECTOR_ALLOWLIST,
    SourceControlPolicyCheck.EVIDENCE_REDACTION,
)
REPOSITORY_READ_CHECKS = (
    *BASE_POLICY_CHECKS,
    SourceControlPolicyCheck.REPOSITORY_CONFIGURED,
    SourceControlPolicyCheck.REPOSITORY_OPERATION_POLICY,
)
WORKSPACE_CHECKS = (
    *REPOSITORY_READ_CHECKS,
    SourceControlPolicyCheck.WORKSPACE_BOUNDARY,
)
REMOTE_WRITE_CHECKS = (
    *WORKSPACE_CHECKS,
    SourceControlPolicyCheck.SECRET_SCOPE_BOUND,
    SourceControlPolicyCheck.APPROVAL_POLICY,
)
DELIVERY_CHECKS = (
    *REPOSITORY_READ_CHECKS,
    SourceControlPolicyCheck.SECRET_SCOPE_BOUND,
    SourceControlPolicyCheck.APPROVAL_POLICY,
)


SOURCE_CONTROL_OPERATION_CONTRACTS: dict[SourceControlOperation, SourceControlOperationContract] = {
    SourceControlOperation.LIST_REPOSITORIES: SourceControlOperationContract(
        operation=SourceControlOperation.LIST_REPOSITORIES,
        repository_operation="read",
        repository_mode=SourceControlRepositoryMode.READONLY,
        mutation=SourceControlMutation.NONE,
        required_policy_checks=BASE_POLICY_CHECKS,
        input_fields=(),
        output_fields=(SourceControlField("repositories", "Configured repositories visible to the actor."),),
        audit_fields=BASE_AUDIT_FIELDS,
        description="List source-control repositories visible through the connector policy.",
    ),
    SourceControlOperation.READ_FILE: SourceControlOperationContract(
        operation=SourceControlOperation.READ_FILE,
        repository_operation="read",
        repository_mode=SourceControlRepositoryMode.READONLY,
        mutation=SourceControlMutation.NONE,
        required_policy_checks=REPOSITORY_READ_CHECKS,
        input_fields=(
            SourceControlField("path", "Repository-relative file path."),
            SourceControlField("ref", "Optional branch, tag, or commit reference.", required=False),
        ),
        output_fields=(
            SourceControlField("content", "Bounded file content."),
            SourceControlField("content_hash", "Optional content digest.", required=False),
        ),
        audit_fields=BASE_AUDIT_FIELDS,
        description="Read a file from a configured repository without exposing provider credentials.",
    ),
    SourceControlOperation.LIST_BRANCHES: SourceControlOperationContract(
        operation=SourceControlOperation.LIST_BRANCHES,
        repository_operation="read",
        repository_mode=SourceControlRepositoryMode.READONLY,
        mutation=SourceControlMutation.NONE,
        required_policy_checks=REPOSITORY_READ_CHECKS,
        input_fields=(SourceControlField("query", "Optional branch filter.", required=False),),
        output_fields=(SourceControlField("branches", "Safe branch summaries."),),
        audit_fields=BASE_AUDIT_FIELDS,
        description="List branches for a configured repository.",
    ),
    SourceControlOperation.CREATE_BRANCH: SourceControlOperationContract(
        operation=SourceControlOperation.CREATE_BRANCH,
        repository_operation="branch",
        repository_mode=SourceControlRepositoryMode.BRANCH,
        mutation=SourceControlMutation.REMOTE,
        required_policy_checks=DELIVERY_CHECKS,
        input_fields=(
            SourceControlField("branch_name", "Branch to create."),
            SourceControlField("start_point", "Safe branch/tag/commit start point."),
        ),
        output_fields=(SourceControlField("branch", "Created branch summary."),),
        audit_fields=(*BASE_AUDIT_FIELDS, SourceControlAuditField.APPROVAL_ID),
        description="Create a branch through a provider connector.",
    ),
    SourceControlOperation.PREPARE_REPOSITORY: SourceControlOperationContract(
        operation=SourceControlOperation.PREPARE_REPOSITORY,
        repository_operation="branch",
        repository_mode=SourceControlRepositoryMode.BRANCH,
        mutation=SourceControlMutation.WORKSPACE,
        required_policy_checks=WORKSPACE_CHECKS,
        input_fields=(
            SourceControlField("base_branch", "Base branch to prepare.", required=False),
            SourceControlField("branch_name", "Local working branch to create."),
        ),
        output_fields=(
            SourceControlField("workspace_ref", "Opaque workspace repository reference."),
            SourceControlField("head_commit", "Prepared repository head commit.", required=False),
        ),
        audit_fields=BASE_AUDIT_FIELDS,
        description="Prepare a local workspace copy using connector-owned credential transport.",
    ),
    SourceControlOperation.COMMIT: SourceControlOperationContract(
        operation=SourceControlOperation.COMMIT,
        repository_operation="write",
        repository_mode=SourceControlRepositoryMode.WRITE,
        mutation=SourceControlMutation.WORKSPACE,
        required_policy_checks=(
            *WORKSPACE_CHECKS,
            SourceControlPolicyCheck.APPROVAL_POLICY,
        ),
        input_fields=(
            SourceControlField("workspace_ref", "Opaque workspace repository reference."),
            SourceControlField("commit_message", "Commit message approved by policy."),
        ),
        output_fields=(SourceControlField("head_commit", "New local head commit."),),
        audit_fields=(*BASE_AUDIT_FIELDS, SourceControlAuditField.APPROVAL_ID),
        description="Commit workspace changes without exposing raw git commands.",
    ),
    SourceControlOperation.PUSH: SourceControlOperationContract(
        operation=SourceControlOperation.PUSH,
        repository_operation="write",
        repository_mode=SourceControlRepositoryMode.WRITE,
        mutation=SourceControlMutation.REMOTE,
        required_policy_checks=REMOTE_WRITE_CHECKS,
        input_fields=(
            SourceControlField("workspace_ref", "Opaque workspace repository reference."),
            SourceControlField("branch_name", "Branch to push."),
        ),
        output_fields=(SourceControlField("remote_ref", "Safe remote branch reference."),),
        audit_fields=(*BASE_AUDIT_FIELDS, SourceControlAuditField.APPROVAL_ID),
        description="Push a provider-owned branch using connector credential transport.",
    ),
    SourceControlOperation.CREATE_CHANGE_REQUEST: SourceControlOperationContract(
        operation=SourceControlOperation.CREATE_CHANGE_REQUEST,
        repository_operation="pr",
        repository_mode=SourceControlRepositoryMode.DELIVERY,
        mutation=SourceControlMutation.REMOTE,
        required_policy_checks=DELIVERY_CHECKS,
        input_fields=(
            SourceControlField("title", "Change request title."),
            SourceControlField("source_branch", "Safe source branch name."),
            SourceControlField("target_branch", "Safe target branch name."),
            SourceControlField("description", "Bounded change request description.", required=False),
        ),
        output_fields=(SourceControlField("change_request", "Safe PR or MR summary."),),
        audit_fields=(*BASE_AUDIT_FIELDS, SourceControlAuditField.APPROVAL_ID),
        description="Create a pull request or merge request through the provider connector.",
    ),
    SourceControlOperation.GET_CHANGE_REQUEST: SourceControlOperationContract(
        operation=SourceControlOperation.GET_CHANGE_REQUEST,
        repository_operation="read",
        repository_mode=SourceControlRepositoryMode.READONLY,
        mutation=SourceControlMutation.NONE,
        required_policy_checks=REPOSITORY_READ_CHECKS,
        input_fields=(SourceControlField("change_request_id", "Provider pull request or merge request id."),),
        output_fields=(SourceControlField("change_request", "Safe PR or MR detail."),),
        audit_fields=BASE_AUDIT_FIELDS,
        description="Read pull request or merge request status for a configured repository.",
    ),
    SourceControlOperation.UPDATE_CHANGE_REQUEST: SourceControlOperationContract(
        operation=SourceControlOperation.UPDATE_CHANGE_REQUEST,
        repository_operation="pr",
        repository_mode=SourceControlRepositoryMode.DELIVERY,
        mutation=SourceControlMutation.REMOTE,
        required_policy_checks=DELIVERY_CHECKS,
        input_fields=(
            SourceControlField("change_request_id", "Provider pull request or merge request id."),
            SourceControlField("title", "Updated change request title.", required=False),
            SourceControlField("description", "Updated change request description.", required=False),
            SourceControlField("target_branch", "Updated target branch.", required=False),
            SourceControlField("reviewers", "Updated reviewer usernames.", required=False),
        ),
        output_fields=(SourceControlField("change_request", "Safe updated PR or MR summary."),),
        audit_fields=(*BASE_AUDIT_FIELDS, SourceControlAuditField.APPROVAL_ID),
        description="Update a pull request or merge request through the provider connector.",
    ),
    SourceControlOperation.LIST_CHANGE_REQUESTS: SourceControlOperationContract(
        operation=SourceControlOperation.LIST_CHANGE_REQUESTS,
        repository_operation="read",
        repository_mode=SourceControlRepositoryMode.READONLY,
        mutation=SourceControlMutation.NONE,
        required_policy_checks=REPOSITORY_READ_CHECKS,
        input_fields=(
            SourceControlField("state", "Provider-neutral change request state.", required=False),
            SourceControlField("branch", "Optional branch filter.", required=False),
        ),
        output_fields=(SourceControlField("change_requests", "Safe PR or MR summaries."),),
        audit_fields=BASE_AUDIT_FIELDS,
        description="List pull requests or merge requests for a configured repository.",
    ),
    SourceControlOperation.LIST_PIPELINES: SourceControlOperationContract(
        operation=SourceControlOperation.LIST_PIPELINES,
        repository_operation="read",
        repository_mode=SourceControlRepositoryMode.READONLY,
        mutation=SourceControlMutation.NONE,
        required_policy_checks=REPOSITORY_READ_CHECKS,
        input_fields=(SourceControlField("ref", "Optional branch or tag reference.", required=False),),
        output_fields=(SourceControlField("pipelines", "Safe CI pipeline summaries."),),
        audit_fields=BASE_AUDIT_FIELDS,
        description="List CI pipeline or action runs associated with a configured repository.",
    ),
}


def get_source_control_operation_contract(
    operation: SourceControlOperation | str,
) -> SourceControlOperationContract:
    normalized = SourceControlOperation(str(operation).strip().lower())
    return SOURCE_CONTROL_OPERATION_CONTRACTS[normalized]


def list_source_control_operation_contracts() -> list[SourceControlOperationContract]:
    return [SOURCE_CONTROL_OPERATION_CONTRACTS[operation] for operation in SourceControlOperation]


__all__ = [
    "FORBIDDEN_PAYLOAD_KEYS",
    "SOURCE_CONTROL_OPERATION_CONTRACTS",
    "SourceControlAuditField",
    "SourceControlContractError",
    "SourceControlField",
    "SourceControlMutation",
    "SourceControlOperation",
    "SourceControlOperationContract",
    "SourceControlOperationRequest",
    "SourceControlOperationResult",
    "SourceControlPolicyCheck",
    "SourceControlProvider",
    "SourceControlRepositoryMode",
    "SourceControlRepositoryRef",
    "get_source_control_operation_contract",
    "list_source_control_operation_contracts",
    "redact_source_control_text",
    "sanitize_source_control_payload",
]
