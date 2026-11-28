"""The scope of a built-in connector kind from its own configuration fields (``config.validate_config``)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .....models.project.knowledge_source_sync import (
    CONNECTOR_KIND_CONFLUENCE,
    CONNECTOR_KIND_GIT_REPOSITORY,
    CONNECTOR_KIND_JIRA,
    CONNECTOR_KIND_KUBERNETES,
    CONNECTOR_KIND_SERVICENOW,
)
from .....tools.jira_impl._jira_jql_confine import jql_is_balanced
from ...ledger.errors import InvalidEvidenceRequestError
from .confluence_scope import CODE_CONFLUENCE_ONLY, SPACE_KEY, InvalidPageTreeError, validate_page_trees
from .git_config import validate_access_mode, validate_git_scope
from .jira_release_config import validate_release_config
from .kinds import pinnable_kinds
from .kubernetes_connection import CLUSTER as KUBERNETES_CLUSTER
from .kubernetes_connection import NAMESPACE as KUBERNETES_NAMESPACE
from .servicenow_scope import validate_servicenow_scope

MAX_SCOPE_KEYS = 20
MAX_KUBERNETES_NAMESPACES = 50
MAX_JQL_CHARS = 500

_SPACE_KEY = SPACE_KEY
_PROJECT_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,49}$")
_ORDER_BY = re.compile(r"\border\s+by\b", re.IGNORECASE)
_CONNECTION_ID = re.compile(r"^[A-Za-z0-9_-]{1,36}$")


@dataclass(frozen=True, slots=True)
class BuiltInFields:
    spaces: object = None
    page_trees: object = None
    project_keys: object = None
    jql: object = None
    knowledge_bases: object = None
    tables: object = None
    article_query: object = None
    record_query: object = None
    releases: object = None
    fetch_mode: object = None
    repository_url: object = None
    ref: object = None
    include_globs: object = None
    exclude_globs: object = None
    max_files: object = None
    max_file_bytes: object = None
    connection_id: object = None
    cluster: object = None
    namespaces: object = None
    access_mode: object = None

    def any_set(self) -> bool:
        return any(getattr(self, name) is not None for name in self.__slots__)

    def servicenow_set(self) -> bool:
        return any(value is not None for value in (self.knowledge_bases, self.tables, self.article_query,
                                                   self.record_query))

    def git(self) -> dict[str, object]:
        return {
            "fetch_mode": self.fetch_mode,
            "repository_url": self.repository_url,
            "ref": self.ref,
            "include_globs": self.include_globs,
            "exclude_globs": self.exclude_globs,
            "max_files": self.max_files,
            "max_file_bytes": self.max_file_bytes,
        }


def check_field_kinds(kind: object, fields: BuiltInFields) -> None:
    if fields.releases is not None and kind != CONNECTOR_KIND_JIRA:
        raise InvalidEvidenceRequestError()
    if fields.page_trees is not None and kind != CONNECTOR_KIND_CONFLUENCE:
        raise InvalidPageTreeError(CODE_CONFLUENCE_ONLY)
    if (kind == CONNECTOR_KIND_GIT_REPOSITORY) != any(value is not None for value in fields.git().values()):
        raise InvalidEvidenceRequestError()
    if (kind == CONNECTOR_KIND_KUBERNETES) != (fields.cluster is not None) or (
        fields.namespaces is not None and kind != CONNECTOR_KIND_KUBERNETES
    ):
        raise InvalidEvidenceRequestError()


def built_in_scope(kind: object, f: BuiltInFields) -> tuple[dict[str, object], dict[str, object] | None]:
    others = (f.spaces, f.project_keys, f.jql)
    if kind == CONNECTOR_KIND_KUBERNETES:
        if any(value is not None for value in others) or f.servicenow_set():
            raise InvalidEvidenceRequestError()
        return validate_kubernetes_scope(cluster=f.cluster, namespaces=f.namespaces), None
    if kind == CONNECTOR_KIND_GIT_REPOSITORY:
        if any(value is not None for value in others) or f.servicenow_set():
            raise InvalidEvidenceRequestError()
        return _git_scope(f)
    if kind == CONNECTOR_KIND_SERVICENOW:
        if any(value is not None for value in others):
            raise InvalidEvidenceRequestError()
        return validate_servicenow_scope(
            knowledge_bases=f.knowledge_bases, tables=f.tables, article_query=f.article_query,
            record_query=f.record_query,
        ), None
    if f.servicenow_set():
        raise InvalidEvidenceRequestError()
    if kind == CONNECTOR_KIND_CONFLUENCE:
        return _confluence_scope(f), None
    if kind == CONNECTOR_KIND_JIRA:
        return _jira_scope(f), None
    raise InvalidEvidenceRequestError()  # a registered kind without validation here is never guessed as Jira


def _git_scope(f: BuiltInFields) -> tuple[dict[str, object], dict[str, object]]:
    git_fields = f.git()
    linked = git_connection(f.connection_id)
    if linked is None and f.access_mode is not None:
        raise InvalidEvidenceRequestError()  # an access mode is what agents may do through a connection
    if linked is not None:
        git_fields["access_mode"] = None if f.access_mode is None else validate_access_mode(f.access_mode)
        # Validated with the connection's host at save (``service.configure_connector``): it may be Data Center.
        return {}, git_fields
    return validate_git_scope(**git_fields), git_fields


def _confluence_scope(f: BuiltInFields) -> dict[str, object]:
    if f.project_keys is not None or f.jql is not None:
        raise InvalidEvidenceRequestError()
    # Whole spaces, page trees, or both; without trees at least one space.
    tree_only = f.page_trees not in (None, []) and f.spaces in (None, [])
    keys = () if tree_only else _keys(f.spaces, _SPACE_KEY, upper=False)
    scope: dict[str, object] = {"spaces": list(keys)}
    trees = validate_page_trees(f.page_trees, spaces=keys)
    if trees:
        scope["page_trees"] = trees
    return scope


def _jira_scope(f: BuiltInFields) -> dict[str, object]:
    if f.spaces is not None:
        raise InvalidEvidenceRequestError()
    keys = _keys(f.project_keys, _PROJECT_KEY, upper=True)
    scope: dict[str, object] = {"project_keys": list(keys), "jql": _jql(f.jql)}
    release_config = validate_release_config(f.releases, project_keys=keys)
    if release_config is not None:
        # Release notes per Jira version (``jira_release_config.py``); absent means off.
        scope["releases"] = release_config
    return scope


def _keys(raw: object, pattern: re.Pattern[str], *, upper: bool) -> tuple[str, ...]:
    if not isinstance(raw, list | tuple) or not raw or len(raw) > MAX_SCOPE_KEYS:
        raise InvalidEvidenceRequestError()
    keys: list[str] = []
    for item in raw:
        if type(item) is not str:
            raise InvalidEvidenceRequestError()
        key = item.strip().upper() if upper else item.strip()
        if not pattern.fullmatch(key):
            raise InvalidEvidenceRequestError()
        keys.append(key)
    return tuple(dict.fromkeys(keys))


def _jql(raw: object) -> str | None:
    if raw is None or (type(raw) is str and not raw.strip()):
        return None
    if type(raw) is not str or len(raw) > MAX_JQL_CHARS or any(ord(ch) < 32 for ch in raw):
        raise InvalidEvidenceRequestError()
    if _ORDER_BY.search(raw) or not jql_is_balanced(raw):
        # An unbalanced quote or parenthesis could break out of the project clause.
        raise InvalidEvidenceRequestError()
    return raw.strip()


def git_connection(raw: object) -> str | None:
    if raw is None or raw == "":
        return None
    if type(raw) is not str or not _CONNECTION_ID.fullmatch(raw) or raw == "default":
        raise InvalidEvidenceRequestError()
    return raw


def validate_kubernetes_scope(*, cluster: object, namespaces: object) -> dict[str, object]:
    if type(cluster) is not str or not KUBERNETES_CLUSTER.fullmatch(cluster.strip()):
        raise InvalidEvidenceRequestError()
    names: tuple[str, ...] = ()
    if namespaces not in (None, []):
        if not isinstance(namespaces, list) or len(namespaces) > MAX_KUBERNETES_NAMESPACES:
            raise InvalidEvidenceRequestError()
        if not all(type(item) is str and KUBERNETES_NAMESPACE.fullmatch(item.strip()) for item in namespaces):
            raise InvalidEvidenceRequestError()
        names = tuple(dict.fromkeys(item.strip() for item in namespaces))
    return {"cluster": cluster.strip(), "namespaces": list(names)}


def connection_pin(kind: str, raw: object) -> str | None:
    if raw is None or raw == "":
        return None
    if kind not in pinnable_kinds() or type(raw) is not str or not _CONNECTION_ID.fullmatch(raw):
        raise InvalidEvidenceRequestError()
    return raw
