"""The registry of Source Sync connector kinds: one entry per kind instead of if/else chains. An unregistered kind is
refused, never read as another kind."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .....models.project.knowledge_source_sync import (
    CONNECTOR_KIND_CONFLUENCE,
    CONNECTOR_KIND_CUSTOM_REST,
    CONNECTOR_KIND_GIT_REPOSITORY,
    CONNECTOR_KIND_JIRA,
    CONNECTOR_KIND_KUBERNETES,
    CONNECTOR_KIND_SERVICENOW,
)
from .confluence import ConfluenceConnector
from .contract import REASON_CONNECTOR_KIND_UNKNOWN, ConnectorError, SourceConnector
from .git_run import git_connector
from .jira import JiraConnector
from .jira_release_config import load_release_config
from .kubernetes import KubernetesConnector
from .servicenow import ServiceNowConnector
from .servicenow_scripted_source import ServiceNowScriptedConnector


@dataclass(frozen=True)
class BuildRequest:
    connection: Any
    row: Any
    transport: Any = None
    db: Any = None
    actor_id: str | None = None

    @property
    def scope(self) -> dict:
        return dict(self.row.scope or {})


@dataclass(frozen=True)
class ConnectorKind:
    kind: str
    build: Callable[[BuildRequest], SourceConnector]
    pinnable: bool = False
    # Kinds configured through the generic admin objects, with a connection of their own (``custom_rest``).
    validate: Callable[[object, object], dict] | None = None
    resolve: Callable[[Any, str, dict], Awaitable[Any]] | None = None
    within: Callable[[dict, Any], bool] | None = None
    describe: Callable[[Any, Any], Awaitable[dict]] | None = None


def _git(request: BuildRequest) -> SourceConnector:
    connection = request.connection  # the named connection passed through, as the egress table test requires
    return git_connector(request.row, transport=request.transport, connection=connection)


def _kubernetes(request: BuildRequest) -> SourceConnector:
    scope = request.scope
    return KubernetesConnector(request.connection, cluster=str(scope.get("cluster") or ""),
                               namespaces=tuple(scope.get("namespaces") or ()), transport=request.transport)


def _confluence(request: BuildRequest) -> SourceConnector:
    scope = request.scope
    return ConfluenceConnector(request.connection, spaces=tuple(scope.get("spaces") or ()),
                               page_trees=tuple(dict(tree) for tree in scope.get("page_trees") or ()),
                               transport=request.transport)


def _servicenow(request: BuildRequest) -> SourceConnector:
    scope = request.scope
    # A Scripted REST connection reads its configured endpoints instead of the Table API.
    factory = ServiceNowScriptedConnector if getattr(request.connection, "api", None) is not None \
        else ServiceNowConnector
    return factory(request.connection, knowledge_bases=tuple(scope.get("knowledge_bases") or ()),
                   tables=tuple(scope.get("tables") or ()), article_filter=scope.get("article_query"),
                   record_filter=scope.get("record_query"), transport=request.transport)


def _jira(request: BuildRequest) -> SourceConnector:
    scope = request.scope
    return JiraConnector(request.connection, project_keys=tuple(scope.get("project_keys") or ()),
                         jql_filter=scope.get("jql"), releases=load_release_config(scope), transport=request.transport)


def _custom_rest(request: BuildRequest) -> SourceConnector:
    from .rest_source import RestKnowledgeConnector

    if request.db is None:
        raise ConnectorError(REASON_CONNECTOR_KIND_UNKNOWN)  # it reads through the executor's session, never without
    return RestKnowledgeConnector(request.connection, scope=request.scope, db=request.db,
                                  project_id=request.row.project_id, actor_id=request.actor_id)


def _validate_rest(scope: object, mapping: object) -> dict:
    from .rest_config import validate_rest_scope

    return validate_rest_scope(scope, mapping)


async def _resolve_rest(db: Any, project_id: str, scope: dict) -> Any:
    from .rest_connection import resolve_rest_connection

    return await resolve_rest_connection(db, project_id, scope)


def _within_rest(scope: dict, connection: Any) -> bool:
    from .rest_connection import rest_scope_within

    return rest_scope_within(scope, connection)


async def _describe_rest(db: Any, row: Any) -> dict:
    from .rest_preview import describe_rest_source

    return await describe_rest_source(db, row)


KINDS: dict[str, ConnectorKind] = {
    entry.kind: entry for entry in (
        ConnectorKind(CONNECTOR_KIND_CONFLUENCE, _confluence, pinnable=True),
        ConnectorKind(CONNECTOR_KIND_JIRA, _jira, pinnable=True),
        ConnectorKind(CONNECTOR_KIND_SERVICENOW, _servicenow, pinnable=True),
        ConnectorKind(CONNECTOR_KIND_KUBERNETES, _kubernetes, pinnable=True),
        ConnectorKind(CONNECTOR_KIND_GIT_REPOSITORY, _git),
        ConnectorKind(CONNECTOR_KIND_CUSTOM_REST, _custom_rest, validate=_validate_rest, resolve=_resolve_rest,
                      within=_within_rest, describe=_describe_rest),
    )
}


def connector_kind(kind: object) -> ConnectorKind:
    # Never another kind's connector.
    entry = KINDS.get(kind) if isinstance(kind, str) else None
    if entry is None:
        raise ConnectorError(REASON_CONNECTOR_KIND_UNKNOWN)
    return entry


def pinnable_kinds() -> frozenset[str]:
    return frozenset(kind for kind, entry in KINDS.items() if entry.pinnable)


__all__ = ["KINDS", "BuildRequest", "ConnectorKind", "connector_kind", "pinnable_kinds"]
