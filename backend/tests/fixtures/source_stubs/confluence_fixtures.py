"""Fixture content of the Confluence stub, and what the source-ACL check expects from it (K6).

One space (``ACLSTUB``) with six pages, one per ACL case the governed Confluence Source Sync
connector must handle (``services/knowledge/sources/sync/confluence.py`` and ``confluence_acl.py``):

| Page | Read restriction | Expected with ``knowledge_source_acl.enforce`` |
|---|---|---|
| 1001 | none | public: every Workspace member |
| 1002 | user ``alice`` | alice only |
| 1003 | none, child of 1002 | alice only (the restriction is inherited) |
| 1004 | group ``acl-stub-readers`` (bob, carol) | bob only (carol has no platform account) |
| 1005 | user ``mallory``, whose address Confluence does not report | nobody (unmapped principal) |
| 1006 | group ``acl-stub-broken``, whose member lookup fails | withheld as ``acl_unresolved`` |

With enforcement off (the default), every restricted page (1002-1006) is withheld as
``restricted_acl`` and only 1001 is ingested.

The platform maps a source principal to a platform user by email address only. The two platform
test users (``PLATFORM_USERS``) carry exactly the addresses the stub reports for alice and bob. The
Workspace owner (the acceptance admin) has an address no page admits, so the owner sees the public
page only: source ACLs have no owner or admin bypass.

``STUB_USERNAME`` / ``STUB_TOKEN`` are the stub's own fixed Basic credential. It protects nothing
and is not a secret; it only proves that the connector sends the Workspace's configured credential.
"""

from __future__ import annotations

SPACE_KEY = "ACLSTUB"
SPACE_NAME = "ACL stub space"
STUB_HOST = "127.0.0.1"
STUB_PORT = 8095
STUB_USERNAME = "octryx-acl-sync"
STUB_TOKEN = "local-stub-token-not-a-secret"
# The one word every page body contains, so one lexical query returns every page a reader may see.
SEARCH_TERM = "quokka"
EMAIL_DOMAIN = "acl-stub.octryx.test"

# Confluence accounts: username -> (userKey, display name, reported address or None).
USERS: dict[str, tuple[str, str, str | None]] = {
    "alice": ("key-alice", "Alice Example", f"alice@{EMAIL_DOMAIN}"),
    "bob": ("key-bob", "Bob Example", f"bob@{EMAIL_DOMAIN}"),
    "carol": ("key-carol", "Carol Example", f"carol@{EMAIL_DOMAIN}"),
    # Exists, but Confluence does not report an address for the account (a hidden profile).
    "mallory": ("key-mallory", "Mallory Example", None),
}

# Confluence groups: name -> member usernames. ``None`` marks a group whose member lookup fails.
GROUPS: dict[str, tuple[str, ...] | None] = {
    "acl-stub-readers": ("bob", "carol"),
    "acl-stub-broken": None,
}

# Pages in listing order (a parent before its children): id -> page.
PAGES: dict[str, dict[str, object]] = {
    "1001": {
        "title": "Onboarding guide",
        "users": (),
        "groups": (),
        "ancestors": (),
        "body": "<p>The quokka onboarding guide is open to the whole space.</p>",
    },
    "1002": {
        "title": "Alice incident notes",
        "users": ("alice",),
        "groups": (),
        "ancestors": (),
        "body": "<p>The quokka incident notes are restricted to Alice.</p>",
    },
    "1003": {
        "title": "Alice incident follow-up",
        "users": (),
        "groups": (),
        "ancestors": ("1002",),
        "body": "<p>The quokka follow-up inherits the restriction of its parent page.</p>",
    },
    "1004": {
        "title": "Readers group roadmap",
        "users": (),
        "groups": ("acl-stub-readers",),
        "ancestors": (),
        "body": "<p>The quokka roadmap is restricted to the readers group.</p>",
    },
    "1005": {
        "title": "Mallory audit log",
        "users": ("mallory",),
        "groups": (),
        "ancestors": (),
        "body": "<p>The quokka audit log is restricted to an account without an address.</p>",
    },
    "1006": {
        "title": "Broken group budget",
        "users": (),
        "groups": ("acl-stub-broken",),
        "ancestors": (),
        "body": "<p>The quokka budget is restricted to a group whose members cannot be listed.</p>",
    },
}

# Platform test users of the local acceptance stack: fixture name -> (username, email).
PLATFORM_USERS: dict[str, tuple[str, str]] = {
    "alice": ("acl-stub-alice", f"alice@{EMAIL_DOMAIN}"),
    "bob": ("acl-stub-bob", f"bob@{EMAIL_DOMAIN}"),
}

PUBLIC_PAGES = frozenset({"1001"})
RESTRICTED_PAGES = frozenset(PAGES) - PUBLIC_PAGES

# Reader -> the page ids knowledge_search and the source listing return, with enforcement on.
# "owner" is the acceptance admin who created the Workspace.
VISIBLE_WITH_ENFORCEMENT: dict[str, frozenset[str]] = {
    "owner": frozenset({"1001"}),
    "alice": frozenset({"1001", "1002", "1003"}),
    "bob": frozenset({"1001", "1004"}),
}
# With enforcement off every reader sees the public page only.
VISIBLE_WITHOUT_ENFORCEMENT: dict[str, frozenset[str]] = dict.fromkeys(VISIBLE_WITH_ENFORCEMENT, PUBLIC_PAGES)

# Page id -> (outcome, reason) of the first sync, with enforcement off and then on.
SYNC_WITHOUT_ENFORCEMENT: dict[str, tuple[str, str | None]] = {
    "1001": ("created", None),
    **{page_id: ("skipped", "restricted_acl") for page_id in sorted(RESTRICTED_PAGES)},
}
SYNC_WITH_ENFORCEMENT: dict[str, tuple[str, str | None]] = {
    "1001": ("unchanged", None),
    "1002": ("created", None),
    "1003": ("created", None),
    "1004": ("created", None),
    "1005": ("created", None),
    "1006": ("skipped", "acl_unresolved"),
}


def page_id_of(source_url: object) -> str | None:
    """The page id in a connector deep link (``…/pages/viewpage.action?pageId=<id>``)."""
    if not isinstance(source_url, str) or "pageId=" not in source_url:
        return None
    return source_url.rsplit("pageId=", 1)[1].split("&", 1)[0] or None
