"""Validation of a connector's per-Workspace configuration.

Values are refused, never cleaned up: a connector key is a short slug, Confluence space keys (and
page trees, ``confluence_scope.py``) and
Jira project keys are the keys those systems use, a JQL filter is bounded and may not carry its own
``ORDER BY`` (the connector owns the order its offset paging depends on), and the product scope is
validated like any upload's. A configured scope must also lie inside the Workspace connection's own
allowlist (``confluence_allowed_spaces``, ``jira_allowed_projects``, ``servicenow_allowed_tables``),
so Source Sync never reads more than the Confluence, Jira and ServiceNow tools of the same Workspace
may. ServiceNow scopes and their encoded queries are validated in ``servicenow_scope.py``, a
``git_repository`` scope (a public repository at a ref, or one read through its linked Bitbucket connection,
whose host is checked at save by ``service.configure_connector``) in ``git_config.py``. A
``kubernetes`` scope is one cluster (the binding of its named connection) and optionally namespaces,
which must lie inside the connection's ``k8s_allowed_namespaces`` when it sets them.

A schedule is off unless ``schedule_enabled`` is true; its interval is bounded
(``MIN_SCHEDULE_INTERVAL_MINUTES`` to ``MAX_SCHEDULE_INTERVAL_MINUTES``), so a connector can never
poll its source system more often than every 15 minutes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .....models.project.knowledge_source_sync import (
    CONNECTOR_KIND_GIT_REPOSITORY,
    CONNECTOR_KINDS,
    CONNECTOR_STATE_ACTIVE,
    CONNECTOR_STATE_PAUSED,
    DEFAULT_SCHEDULE_INTERVAL_MINUTES,
)
from ...ledger.errors import InvalidEvidenceRequestError
from ..scope import normalize_products, normalize_version
from .config_fields import BuiltInFields, built_in_scope, check_field_kinds, connection_pin, git_connection
from .kinds import KINDS

MAX_ITEMS_PER_RUN = 500
DEFAULT_ITEMS_PER_RUN = 100
MIN_SCHEDULE_INTERVAL_MINUTES = 15
MAX_SCHEDULE_INTERVAL_MINUTES = 7 * 24 * 60

_CONNECTOR_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


@dataclass(frozen=True, slots=True)
class ConnectorConfig:
    connector_key: str
    kind: str
    scope: dict[str, object]
    products: tuple[str, ...]
    version: str | None
    max_items_per_run: int
    state: str
    schedule_enabled: bool = False
    schedule_interval_minutes: int = DEFAULT_SCHEDULE_INTERVAL_MINUTES
    # git_repository linked to a connection (the source's ``connection_id``): its git fields are validated against
    # that connection's host at save (``service.configure_connector``), ``scope`` holds them until then.
    connection_id: str | None = None
    git_fields: dict[str, object] | None = None


def validate_config(
    *,
    connector_key: object,
    kind: object,
    spaces: object = None,
    page_trees: object = None,
    project_keys: object = None,
    jql: object = None,
    products: object = None,
    version: object = None,
    max_items_per_run: object = None,
    state: object = None,
    knowledge_bases: object = None,
    tables: object = None,
    article_query: object = None,
    record_query: object = None,
    schedule_enabled: object = None,
    schedule_interval_minutes: object = None,
    releases: object = None,
    fetch_mode: object = None,
    repository_url: object = None,
    ref: object = None,
    include_globs: object = None,
    exclude_globs: object = None,
    max_files: object = None,
    max_file_bytes: object = None,
    connection_id: object = None,
    cluster: object = None,
    namespaces: object = None,
    access_mode: object = None,
    scope: object = None,
    mapping: object = None,
) -> ConnectorConfig:
    if type(connector_key) is not str or not _CONNECTOR_KEY.fullmatch(connector_key):
        raise InvalidEvidenceRequestError()
    if kind not in CONNECTOR_KINDS or kind not in KINDS:
        raise InvalidEvidenceRequestError()
    entry = KINDS[kind]
    shared = {"products": products, "version": version, "max_items_per_run": max_items_per_run, "state": state,
              "schedule_enabled": schedule_enabled, "schedule_interval_minutes": schedule_interval_minutes}
    fields = BuiltInFields(
        spaces=spaces, page_trees=page_trees, project_keys=project_keys, jql=jql, knowledge_bases=knowledge_bases,
        tables=tables, article_query=article_query, record_query=record_query, releases=releases,
        fetch_mode=fetch_mode, repository_url=repository_url, ref=ref, include_globs=include_globs,
        exclude_globs=exclude_globs, max_files=max_files, max_file_bytes=max_file_bytes, connection_id=connection_id,
        cluster=cluster, namespaces=namespaces, access_mode=access_mode,
    )
    if entry.validate is not None:
        # A kind configured through the generic objects (``custom_rest``): no other kind's field applies to it.
        if fields.any_set():
            raise InvalidEvidenceRequestError()
        return _finish(connector_key, kind, entry.validate(scope, mapping), **shared)
    if scope is not None or mapping is not None:
        raise InvalidEvidenceRequestError()  # the built-in kinds keep their own fields
    return _built_in(connector_key, kind, fields, shared)


def _built_in(connector_key: str, kind: str, fields: BuiltInFields, shared: dict[str, object]) -> ConnectorConfig:
    check_field_kinds(kind, fields)
    scope, git_fields = built_in_scope(kind, fields)
    if fields.access_mode is not None and kind != CONNECTOR_KIND_GIT_REPOSITORY:
        raise InvalidEvidenceRequestError()
    pin = None if kind == CONNECTOR_KIND_GIT_REPOSITORY else connection_pin(kind, fields.connection_id)
    if pin is not None:
        scope["connection_id"] = pin
    return _finish(
        connector_key, kind, scope, **shared,
        connection_id=git_connection(fields.connection_id) if kind == CONNECTOR_KIND_GIT_REPOSITORY else None,
        git_fields=git_fields if kind == CONNECTOR_KIND_GIT_REPOSITORY and not scope else None,
    )


def _finish(
    connector_key: str, kind: str, scope: dict[str, object], *, products: object, version: object,
    max_items_per_run: object, state: object, schedule_enabled: object, schedule_interval_minutes: object,
    connection_id: str | None = None, git_fields: dict[str, object] | None = None,
) -> ConnectorConfig:
    """The settings every kind shares: products, run budget, state and schedule."""
    limit = DEFAULT_ITEMS_PER_RUN if max_items_per_run is None else max_items_per_run
    if type(limit) is not int or not 1 <= limit <= MAX_ITEMS_PER_RUN:
        raise InvalidEvidenceRequestError()
    run_state = CONNECTOR_STATE_ACTIVE if state is None else state
    if run_state not in (CONNECTOR_STATE_ACTIVE, CONNECTOR_STATE_PAUSED):
        raise InvalidEvidenceRequestError()
    enabled = False if schedule_enabled is None else schedule_enabled
    interval = DEFAULT_SCHEDULE_INTERVAL_MINUTES if schedule_interval_minutes is None else schedule_interval_minutes
    if type(enabled) is not bool or type(interval) is not int:
        raise InvalidEvidenceRequestError()
    if not MIN_SCHEDULE_INTERVAL_MINUTES <= interval <= MAX_SCHEDULE_INTERVAL_MINUTES:
        raise InvalidEvidenceRequestError()
    scope_products = normalize_products(products)
    scope_version = normalize_version(version)
    if scope_version is not None and not scope_products:
        # A version is always the version of a product, as for uploads.
        raise InvalidEvidenceRequestError()
    return ConnectorConfig(
        connector_key=connector_key,
        kind=kind,
        scope=scope,
        products=scope_products,
        version=scope_version,
        max_items_per_run=limit,
        state=run_state,
        schedule_enabled=enabled,
        schedule_interval_minutes=interval,
        connection_id=connection_id,
        git_fields=git_fields,
    )


__all__ = ["MAX_SCHEDULE_INTERVAL_MINUTES", "MIN_SCHEDULE_INTERVAL_MINUTES", "ConnectorConfig", "validate_config"]
