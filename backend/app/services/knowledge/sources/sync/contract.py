"""The Source Sync port: what a connector hands the runner, and nothing more."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

ACL_AUDIENCE_SCOPE = "scope"  # everyone who can read the configured space/project can read it
ACL_AUDIENCE_RESTRICTED = "restricted"  # narrower than the scope: ingested only with its ACL
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
# The Workspace's own connection is set but not usable; it never falls back to the global one.
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
# Not a failure: the reason a completed run carries when the repository has no commits yet.
REASON_REPOSITORY_EMPTY = "repository_empty"
# A ``local_snapshot`` connector has nothing to fetch: its files arrive only with an upload.
REASON_SNAPSHOT_UPLOAD_REQUIRED = "snapshot_upload_required"
# An Atlassian Cloud Confluence URL without its ``/wiki`` context path (same rule as the connection test).
REASON_CONFLUENCE_CLOUD_URL_WITHOUT_WIKI = "confluence_cloud_url_without_wiki"
# A scope item no connection may serve, or one connector whose items need different connections.
REASON_CONNECTION_NOT_CONFIGURED_FOR_SCOPE = "connection_not_configured_for_scope"
REASON_SCOPE_SPANS_CONNECTIONS = "scope_spans_connections"
# A pinned connector whose items resolve to another or a missing connection: never read with that account.
REASON_CONNECTION_PIN_MISMATCH = "connection_pin_mismatch"
REASON_CONNECTION_PIN_UNKNOWN = "connection_pin_unknown"
# The source's linked connection (``connection_id``) refuses the run (``named_connections/linked_use``).
REASON_CONNECTION_DISABLED = "connection_disabled"
REASON_CONNECTION_NOT_AVAILABLE = "connection_not_available"
REASON_CONNECTION_USE_DISABLED = "connection_use_disabled"
REASON_CONNECTION_AMBIGUOUS = "connection_ambiguous"
# A repository not on its connection's host, or a connection type that reads no repositories.
REASON_REPOSITORY_NOT_ON_CONNECTION_HOST = "repository_not_on_connection_host"
# Several usable connections could read an unlinked source: an author must choose; never a guessed account.
REASON_CONNECTION_CHOICE_REQUIRED = "connection_choice_required"
# Bitbucket refused the repository's own Git token, or it does not reach exactly that repository.
REASON_GIT_TOKEN_INVALID = "git_token_invalid"
REASON_GIT_TOKEN_WRONG_REPOSITORY = "git_token_wrong_repository"
REASON_GIT_TOKEN_NOT_SUPPORTED = "git_token_not_supported"
WITHHELD_REASONS = frozenset({"restricted_acl", "acl_unresolved"})


class ConnectorError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class AclFacet:
    # ``complete`` False (the bound cut principals off) makes the facet unusable for enforcement.
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
    # Unmapped members map to no platform user, so the restriction admits them nobody.
    member_emails: tuple[str, ...] = field(repr=False)
    unmapped: int = 0


@dataclass(frozen=True, slots=True)
class SourceItem:
    external_id: str
    title: str
    source_url: str
    version_marker: str
    acl: AclFacet
    products: tuple[str, ...] = ()
    version: str | None = None
    role: str | None = None
    #: When the item last changed at its source; ``None`` when the source does not say.
    source_changed_at: datetime | None = None
    #: The base URL of the connection the item was read through; never a link from the response.
    read_base: str | None = None


@dataclass(frozen=True, slots=True)
class ItemContent:
    data: bytes = field(repr=False)
    media_type: str
    code_file: object | None = None


@dataclass(frozen=True, slots=True)
class ListingPage:
    items: tuple[SourceItem, ...]
    next_token: str | None
    deleted: tuple[str, ...] = ()
    skipped: tuple[tuple[str, str], ...] = ()


class SourceConnector(Protocol):
    kind: str
    requires_parser: bool

    async def list_items(self, token: str | None, *, limit: int) -> ListingPage: ...

    async def fetch(self, item: SourceItem) -> ItemContent: ...

    # Optional ``list_changed_items(token, *, since, limit)`` (Confluence CQL) gives incremental scheduled runs;
    # without it a connector always lists fully.

    async def expand_acl(self, acl: AclFacet) -> AclExpansion | None:
        # ``None``: this connector cannot expand the mechanism, and the item stays withheld.
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
