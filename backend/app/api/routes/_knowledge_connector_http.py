"""Request bodies, fixed refusals and lookups of the Workspace Knowledge connector routes."""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, SecretStr

from app.services.knowledge.sources.sync.confluence_scope import InvalidPageTreeError

from ...models.project.knowledge_source_sync import CONNECTOR_KINDS
from ...services.knowledge.access.authorization import (
    WORKSPACE_WRITE_FORBIDDEN_DETAIL,
    AuthorizedWorkspace,
    WorkspaceWriteForbiddenError,
    authorize_workspace,
)
from ...services.knowledge.ledger.errors import EvidenceLedgerError
from ...services.knowledge.sources.sync.git_autolink import ConnectionChoiceRequiredError
from ...services.knowledge.sources.sync.jira_release_config import InvalidReleaseConfigError
from ...services.knowledge.sources.sync.rest_config import InvalidRestSourceError
from ...services.knowledge.sources.sync.service import get_connector
from ._knowledge_evidence_http import evidence_http_error

# The registered kinds (``models.project.knowledge_source_sync.CONNECTOR_KINDS``): one list, never a second copy here.
ConnectorKindName = Literal[tuple(sorted(CONNECTOR_KINDS))]  # type: ignore[valid-type]


class ConnectorConfigBody(BaseModel):
    kind: ConnectorKindName
    spaces: list[str] | None = Field(default=None, max_length=20)
    # Confluence page trees ``[{space_key, root_page_id}]``; validated with fixed codes (422).
    page_trees: list | None = None
    project_keys: list[str] | None = Field(default=None, max_length=20)
    jql: str | None = Field(default=None, max_length=500)
    # ServiceNow: knowledge base sys_ids and record tables, each narrowed by an optional encoded query.
    knowledge_bases: list[str] | None = Field(default=None, max_length=20)
    tables: list[str] | None = Field(default=None, max_length=2)
    article_query: str | None = Field(default=None, max_length=500)
    record_query: str | None = Field(default=None, max_length=500)
    # Jira only: release notes per Jira version (project -> product mapping, prefixes, sections).
    releases: dict | None = None
    # git_repository only: a public repository on a known host at a ref (a commit sha, branch or tag), or, with
    # ``connection_id``, a repository on that Bitbucket connection's host (Data Center: its URL; Cloud:
    # bitbucket.org) read with its credential. A local_snapshot connector is created by its upload, never here.
    fetch_mode: Literal["remote_git"] | None = None
    repository_url: str | None = Field(default=None, max_length=300)
    ref: str | None = Field(default=None, max_length=100)
    include_globs: list[str] | None = Field(default=None, max_length=20)
    exclude_globs: list[str] | None = Field(default=None, max_length=20)
    max_files: int | None = Field(default=None, ge=1, le=5000)
    max_file_bytes: int | None = Field(default=None, ge=1024, le=2 * 1024 * 1024)
    # kubernetes only: the cluster (a named connection's binding) and optionally some of its namespaces.
    cluster: str | None = Field(default=None, max_length=128)
    namespaces: list[str] | None = Field(default=None, max_length=50)
    # Confluence, Jira, ServiceNow, Kubernetes: read only with this named connection (its id, or "default").
    # Unset: each scope item uses the connection that binds it. git_repository: the connection the source is linked
    # to (``knowledge_source_connectors.connection_id``), which reads the repository.
    connection_id: str | None = Field(default=None, max_length=36)
    # git_repository linked to a Bitbucket connection: what agents may do on it through the connection (default
    # read_only; omitted on a re-save: unchanged).
    access_mode: Literal["read_only", "read_write"] | None = None
    # custom_rest: the generic configuration objects of a kind without fields of its own here, validated
    # and size-capped by the kind (``sync/rest_config.py``); refused for every built-in kind.
    scope: dict | None = None
    mapping: dict | None = None
    # Off by default; scheduled runs also need the Instance switch and act as the saving author.
    schedule_enabled: bool | None = None
    schedule_interval_minutes: int | None = Field(default=None, ge=15, le=10080)
    products: list[str] | None = Field(default=None, max_length=8)
    version: str | None = Field(default=None, max_length=40)
    max_items_per_run: int | None = Field(default=None, ge=1, le=500)
    state: Literal["active", "paused"] | None = None
    # git_repository on a Bitbucket Data Center connection: the repository's own Git token (a
    # Bitbucket HTTP access token), checked against exactly that repository, stored encrypted, never answered.
    # Omitted on a re-save: unchanged. No length constraint here, so a refusal never echoes the value (422 input);
    # never part of model_dump(), so it never reaches the configuration or its audit.
    git_token: SecretStr | None = Field(default=None, exclude=True)


class AccessModeBody(BaseModel):
    access_mode: Literal["read_only", "read_write"]


class GitTokenBody(BaseModel):
    git_token: SecretStr


def _secret(value: SecretStr | None) -> str | None:
    return None if value is None else value.get_secret_value()


def _refusal(reason: str) -> HTTPException:
    """A connector that cannot act now: the fixed reason tells an author what to configure."""
    return HTTPException(status_code=409, detail={"state": "refused", "reason": reason})


def _field_refusal(error: InvalidPageTreeError | InvalidRestSourceError) -> HTTPException:
    """A refused setting with its fixed code and field (422), for the editor to show next to that field."""
    return HTTPException(status_code=422, detail={"state": "invalid_request", "reason": error.code,
                                                  "field": error.field})


def _choice_required(error: ConnectionChoiceRequiredError) -> HTTPException:
    """Several connections could read the repository: the author picks one (``connection_id``) from ``candidates``."""
    return HTTPException(status_code=422, detail={"state": "invalid_request", "reason": error.reason,
                                                  "field": "connection_id", "candidates": error.candidates})


def release_config_refusal(error: InvalidReleaseConfigError) -> HTTPException:
    """A refused ``releases`` value: the field path and fixed code an editor shows next to that field."""
    return HTTPException(
        status_code=400, detail={"state": "invalid_request", "reason": error.code, "field": error.field}
    )


async def _authorized(db, user, workspace_id: str, *, author: bool) -> AuthorizedWorkspace:
    try:
        return await authorize_workspace(db, current_user=user, workspace_id=workspace_id, require_author=author)
    except WorkspaceWriteForbiddenError:
        raise HTTPException(status_code=403, detail=WORKSPACE_WRITE_FORBIDDEN_DETAIL) from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None


async def _connector(db, authorized: AuthorizedWorkspace, connector_key: str):
    try:
        return await get_connector(db, authorized, connector_key)
    except EvidenceLedgerError:
        raise HTTPException(status_code=404, detail="Knowledge connector not found.") from None
