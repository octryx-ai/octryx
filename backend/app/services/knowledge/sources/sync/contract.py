"""The Source Sync port: what a connector hands the runner, and nothing more.

A connector enumerates the items of its configured scope in **listing passes**. Each call returns
one bounded page of :class:`SourceItem` headers and an opaque token for the next page; ``None``
ends the pass. A header is cheap (no body): the stable external id, the title, the deep link, the
external version marker and the ACL facet. The runner fetches the content (:class:`ItemContent`)
only for an item whose version marker changed, and ingests it only when its content hash changed.

Deletions are tombstones in two forms, both explicit:

- ``ListingPage.deleted``: ids the source reports as removed (a connector that can see its trash);
- an ingested item that a **completed** pass did not list any more. A pass that stops early
  (budget, failure) never retires anything, so a partial listing cannot look like a deletion.

The ACL facet is captured for every item. An item readable by the whole configured audience is
ingested. A restricted item is ingested only when the Workspace enforces source ACLs
(``access/source_acl.py``) and the connector can expand its facet to member email
addresses (:meth:`SourceConnector.expand_acl`); otherwise it is withheld (``restricted_acl``). An
item whose ACL could not be determined, or not expanded within bounds, is never ingested
(``acl_unresolved``).

Errors carry a fixed reason only; no response body, URL or credential ever leaves a connector.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

# The audience of one item, relative to the configured scope (a space, a project).
ACL_AUDIENCE_SCOPE = "scope"  # everyone who can read the configured space/project can read it
ACL_AUDIENCE_RESTRICTED = "restricted"  # narrower than the scope: ingested only with its ACL (5b)
ACL_AUDIENCE_UNKNOWN = "unknown"  # could not be determined: never ingested

MAX_ACL_PRINCIPALS = 20

# Fixed per-item and per-run reasons. The runner records only these, never free text.
REASON_RESTRICTED_ACL = "restricted_acl"
REASON_ACL_UNRESOLVED = "acl_unresolved"
REASON_REMOVED_AT_SOURCE = "removed_at_source"
REASON_SOURCE_UNAUTHORIZED = "source_unauthorized"
REASON_SOURCE_NOT_FOUND = "source_not_found"
REASON_SOURCE_RATE_LIMITED = "source_rate_limited"
REASON_SOURCE_UNAVAILABLE = "source_unavailable"
REASON_SOURCE_CONTRACT_VIOLATION = "source_contract_violation"
REASON_LISTING_STALLED = "listing_stalled"
REASON_CONNECTION_NOT_CONFIGURED = "connection_not_configured"
# The Workspace's own connection is set but not usable: no own URL beside an own secret, or no
# credential for its auth mode. It never falls back to the global connection.
REASON_OWN_CONNECTION_INCOMPLETE = "own_connection_incomplete"
REASON_PARSER_NOT_CONFIGURED = "parser_not_configured"
REASON_RUN_IN_PROGRESS = "run_in_progress"
REASON_CONNECTOR_PAUSED = "connector_paused"
# A stored or requested kind the registry does not know (``kinds.py``): refused, never read as another kind.
REASON_CONNECTOR_KIND_UNKNOWN = "connector_kind_unknown"
REASON_SCOPE_NOT_ALLOWED = "scope_not_allowed"
REASON_WORKSPACE_INACTIVE = "workspace_inactive"  # the Workspace project is deleted or archived
# The connection's URL resolves to a loopback, link-local, private or metadata address.
REASON_EGRESS_REFUSED = "egress_refused"
# A repository commit holds more files or bytes than its connector admits (``git_repository``).
REASON_REPOSITORY_TOO_LARGE = "repository_too_large"
# Not a failure (an empty repository is a normal start): the reason a *completed* run carries
# when the repository exists and is reachable but has no commits yet (no branch, no tag, no default branch). The run
# lists 0 items; Knowledge › Sources and Work › Repositories say "Empty repository — ready for a first commit", and
# the Problems list never reports it (it reports failed runs only).
REASON_REPOSITORY_EMPTY = "repository_empty"
# A ``local_snapshot`` connector has nothing to fetch: its files arrive only with an upload.
REASON_SNAPSHOT_UPLOAD_REQUIRED = "snapshot_upload_required"
# An Atlassian Cloud Confluence URL without its ``/wiki`` context path (same rule as the connection test).
REASON_CONFLUENCE_CLOUD_URL_WITHOUT_WIKI = "confluence_cloud_url_without_wiki"
# Named connections: a scope item no connection may serve, or (Jira, ServiceNow) one connector
# whose scope items are served by different connections (configure one connector per connection).
REASON_CONNECTION_NOT_CONFIGURED_FOR_SCOPE = "connection_not_configured_for_scope"
REASON_SCOPE_SPANS_CONNECTIONS = "scope_spans_connections"
# A connector pinned to one connection by id (``scope.connection_id``) whose scope items resolve to another
# connection, or to a connection that no longer exists: refused, never read with the other account.
REASON_CONNECTION_PIN_MISMATCH = "connection_pin_mismatch"
REASON_CONNECTION_PIN_UNKNOWN = "connection_pin_unknown"
# The source's linked connection (``connection_id``) refuses the run (``named_connections/linked_use``).
REASON_CONNECTION_DISABLED = "connection_disabled"
REASON_CONNECTION_NOT_AVAILABLE = "connection_not_available"
REASON_CONNECTION_USE_DISABLED = "connection_use_disabled"
REASON_CONNECTION_AMBIGUOUS = "connection_ambiguous"
# A repository saved with a connection that is not on that connection's host (Bitbucket Data Center: its URL;
# Bitbucket Cloud: bitbucket.org), or a connection of a type that reads no repositories.
REASON_REPOSITORY_NOT_ON_CONNECTION_HOST = "repository_not_on_connection_host"
# A ``git_repository`` source without a connection that several usable connections could read (``git_autolink.py``):
# an author must choose one (``connection_id``); the source is never read anonymously or with a guessed account.
REASON_CONNECTION_CHOICE_REQUIRED = "connection_choice_required"
# A per-repository Git token (``repository_git_token.py``): Bitbucket refused it (401, or not a token
# at all), it does not reach exactly the registered repository (403/404, or another repository answered), or the
# source is no Bitbucket Data Center repository read through its connection.
REASON_GIT_TOKEN_INVALID = "git_token_invalid"
REASON_GIT_TOKEN_WRONG_REPOSITORY = "git_token_wrong_repository"
REASON_GIT_TOKEN_NOT_SUPPORTED = "git_token_not_supported"
# Restricted items not ingested in one run (``restricted_acl`` and ``acl_unresolved``), counted.
WITHHELD_REASONS = frozenset({"restricted_acl", "acl_unresolved"})


class ConnectorError(Exception):
    """A source-system call failed; ``reason`` is one of the fixed reasons above."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class AclFacet:
    """Who may read one item, mirrored from the source system.

    ``restriction`` names the mechanism (``page_restriction``, ``ancestor_restriction``,
    ``issue_security_level``); ``principals`` are the users, groups or level names it admits, bounded.
    ``complete`` is False when the bound cut some off, which makes the facet unusable for enforcement.
    """

    audience: str
    restriction: str | None = None
    principals: tuple[str, ...] = ()
    complete: bool = True

    @classmethod
    def scope(cls) -> AclFacet:
        return cls(audience=ACL_AUDIENCE_SCOPE)

    @classmethod
    def restricted(cls, restriction: str, principals: tuple[str, ...] = ()) -> AclFacet:
        principals = tuple(principals)
        return cls(
            ACL_AUDIENCE_RESTRICTED,
            restriction,
            principals[:MAX_ACL_PRINCIPALS],
            complete=len(principals) <= MAX_ACL_PRINCIPALS,
        )

    @classmethod
    def unknown(cls) -> AclFacet:
        return cls(audience=ACL_AUDIENCE_UNKNOWN)

    def as_dict(self) -> dict[str, object]:
        return {"audience": self.audience, "restriction": self.restriction, "principals": list(self.principals)}


@dataclass(frozen=True, slots=True)
class AclExpansion:
    """A restricted facet expanded to the email addresses the source system reports for its members.

    ``unmapped`` counts members the source reported without a usable address: they map to no
    platform user, so the restriction admits them nobody.
    """

    member_emails: tuple[str, ...] = field(repr=False)
    unmapped: int = 0


@dataclass(frozen=True, slots=True)
class SourceItem:
    """One item header of a listing page. ``source_url`` must pass ``normalize_source_url``.

    ``products`` and ``version``, when the item carries products, replace the connector's configured
    product scope for this one item (a Jira release is the knowledge of its own product version).
    ``role`` is the document role the item's source ranks with (``release_notes``); ``None`` for none.
    """

    external_id: str
    title: str
    source_url: str
    version_marker: str
    acl: AclFacet
    products: tuple[str, ...] = ()
    version: str | None = None
    role: str | None = None
    #: When the item last changed at its source (Confluence version.when, Jira fields.updated, ServiceNow
    #: sys_updated_on, the synced commit's date); ``None`` when the source does not say. Shown as the hit's date.
    source_changed_at: datetime | None = None
    #: The base URL of the connection the item was actually read through (provenance, ``provenance.py``); never a
    #: link from the response. ``None`` for connectors that read no Confluence.
    read_base: str | None = None


@dataclass(frozen=True, slots=True)
class ItemContent:
    """The bytes of one item and their declared media type (text-native or sandboxed).

    ``code_file`` (a ``code.facets.CodeFileFacet``) marks a repository file: it is ingested as code,
    with line-ranged spans and its repository, path, language and commit facets.
    """

    data: bytes = field(repr=False)
    media_type: str
    code_file: object | None = None


@dataclass(frozen=True, slots=True)
class ListingPage:
    """``skipped``: (external id, fixed reason) of listed entries that are not items and never ingested."""

    items: tuple[SourceItem, ...]
    next_token: str | None
    deleted: tuple[str, ...] = ()
    skipped: tuple[tuple[str, str], ...] = ()


class SourceConnector(Protocol):
    """A source system, already bound to one Workspace's connection and configured scope."""

    kind: str
    # True when the content must go through the parser sandbox (HTML, PDF, Office).
    requires_parser: bool

    async def list_items(self, token: str | None, *, limit: int) -> ListingPage: ...

    async def fetch(self, item: SourceItem) -> ItemContent: ...

    # Optional: ``list_changed_items(token, *, since, limit)`` lists only the items changed
    # since an instant (Confluence CQL). A connector that has it gets incremental scheduled runs
    # between full reconciliation passes; one without it always lists fully.

    async def expand_acl(self, acl: AclFacet) -> AclExpansion | None:
        """Expand a restricted facet to member addresses, bounded.

        ``None``: this connector cannot expand this mechanism (the item stays withheld). A lookup
        that fails or exceeds its bounds raises :class:`ConnectorError` with ``acl_unresolved``.
        """
        ...


__all__ = [
    "ACL_AUDIENCE_RESTRICTED",
    "ACL_AUDIENCE_SCOPE",
    "ACL_AUDIENCE_UNKNOWN",
    "REASON_ACL_UNRESOLVED",
    "REASON_CONFLUENCE_CLOUD_URL_WITHOUT_WIKI",
    "REASON_CONNECTION_NOT_CONFIGURED",
    "REASON_CONNECTION_NOT_CONFIGURED_FOR_SCOPE",
    "REASON_CONNECTION_PIN_MISMATCH",
    "REASON_CONNECTION_PIN_UNKNOWN",
    "REASON_CONNECTION_AMBIGUOUS",
    "REASON_CONNECTION_CHOICE_REQUIRED",
    "REASON_CONNECTION_DISABLED",
    "REASON_CONNECTION_NOT_AVAILABLE",
    "REASON_CONNECTION_USE_DISABLED",
    "REASON_OWN_CONNECTION_INCOMPLETE",
    "REASON_CONNECTOR_KIND_UNKNOWN",
    "REASON_CONNECTOR_PAUSED",
    "REASON_GIT_TOKEN_INVALID",
    "REASON_GIT_TOKEN_NOT_SUPPORTED",
    "REASON_GIT_TOKEN_WRONG_REPOSITORY",
    "REASON_LISTING_STALLED",
    "REASON_PARSER_NOT_CONFIGURED",
    "REASON_REPOSITORY_EMPTY",
    "REASON_REPOSITORY_TOO_LARGE",
    "REASON_REMOVED_AT_SOURCE",
    "REASON_RESTRICTED_ACL",
    "REASON_RUN_IN_PROGRESS",
    "REASON_SCOPE_NOT_ALLOWED",
    "REASON_SCOPE_SPANS_CONNECTIONS",
    "REASON_SNAPSHOT_UPLOAD_REQUIRED",
    "REASON_SOURCE_CONTRACT_VIOLATION",
    "REASON_SOURCE_NOT_FOUND",
    "REASON_SOURCE_RATE_LIMITED",
    "REASON_SOURCE_UNAUTHORIZED",
    "REASON_SOURCE_UNAVAILABLE",
    "AclExpansion",
    "AclFacet",
    "ConnectorError",
    "ItemContent",
    "ListingPage",
    "SourceConnector",
    "SourceItem",
    "WITHHELD_REASONS",
]
