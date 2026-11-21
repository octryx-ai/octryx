"""Content-addressed, Workspace-partitioned object keys.

A key is derived only from the validated :class:`WorkspaceId`, the optional
configured prefix, and the lower-case hex SHA-256 of the bytes:

    ``<prefix>/knowledge/octryx_ws_<32 hex>/sha256/<aa>/<bb>/<64 hex>``

Consequences that the rest of the slice depends on:

- nothing user-supplied (no file name, no display title, no media type) is part
  of a key, so a key can never carry path, query-language, or control syntax;
- the Workspace segment is derived only from the canonical Workspace UUID
  (``octryx_ws_<32 hex>``), so one Workspace identity produces one partition;
- identical bytes in two Workspaces produce two different keys, and existence is
  probed only inside the caller's own partition, so no Workspace can learn that
  another holds the same document;
- the key is a pure function of the digest, which makes the write idempotent:
  re-uploading the same bytes addresses the object that is already there.
"""

from __future__ import annotations

import re

from ..identity.workspace import WorkspaceId
from ..retrieval.errors import InvalidWorkspaceError
from .errors import KnowledgeObjectContractError, KnowledgeObjectOperation

CONTENT_ROOT_SEGMENT = "knowledge"
WORKSPACE_SEGMENT_PREFIX = "octryx_ws_"
DIGEST_SEGMENT = "sha256"

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
# The full derivation, re-checked after building it: the only shapes that may
# ever reach the S3 client.
_OBJECT_KEY = re.compile(
    r"^(?:[a-z0-9][a-z0-9_-]*(?:/[a-z0-9][a-z0-9_-]*)*/)?"
    r"knowledge/octryx_ws_[0-9a-f]{32}/sha256/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{64}$"
)


def workspace_object_prefix(prefix: str | None, workspace: WorkspaceId) -> str:
    """Return the key prefix that bounds one Workspace's objects."""
    if type(workspace) is not WorkspaceId:
        raise InvalidWorkspaceError()
    # Revalidated: rejects subclasses and in-place mutation of the identity.
    segment = f"{WORKSPACE_SEGMENT_PREFIX}{WorkspaceId.parse(workspace).value.hex}"
    root = f"{CONTENT_ROOT_SEGMENT}/{segment}"
    if prefix is None:
        return root
    if type(prefix) is not str or not prefix:
        raise KnowledgeObjectContractError(KnowledgeObjectOperation.CONFIGURATION)
    return f"{prefix}/{root}"


def workspace_object_key(prefix: str | None, workspace: WorkspaceId, content_sha256: object) -> str:
    """Derive the single object key that holds ``content_sha256`` for a Workspace."""
    if type(content_sha256) is not str or not _SHA256_HEX.fullmatch(content_sha256):
        raise KnowledgeObjectContractError(KnowledgeObjectOperation.CONFIGURATION)
    fan_out = f"{content_sha256[0:2]}/{content_sha256[2:4]}"
    key = f"{workspace_object_prefix(prefix, workspace)}/{DIGEST_SEGMENT}/{fan_out}/{content_sha256}"
    # Defense in depth: only the fixed derivation ever reaches the S3 client.
    if not _OBJECT_KEY.fullmatch(key):
        raise KnowledgeObjectContractError(KnowledgeObjectOperation.CONFIGURATION)
    return key


def content_digest_from_key(key: object) -> str | None:
    """The content address ``key`` encodes, or ``None`` when it is not a derived key.

    Used by the operator-owned inventory: an object that sits under a Workspace
    prefix but whose key is not exactly this module's derivation — fan-out segments
    included — has no known content address, so it is counted and never becomes a deletion
    candidate.
    """
    if type(key) is not str or not _OBJECT_KEY.fullmatch(key):
        return None
    digest = key.rsplit("/", 1)[-1]
    if not key.endswith(f"/{DIGEST_SEGMENT}/{digest[0:2]}/{digest[2:4]}/{digest}"):
        return None
    return digest


def is_key_inside_workspace(key: object, prefix: str | None, workspace: WorkspaceId) -> bool:
    """True when ``key`` lies in exactly this Workspace's partition.

    Used before reading a persisted key, so a ledger row that was tampered with
    (or written under a different prefix) cannot make one Workspace read
    another Workspace's object.
    """
    if type(key) is not str or not _OBJECT_KEY.fullmatch(key):
        return False
    return key.startswith(f"{workspace_object_prefix(prefix, workspace)}/{DIGEST_SEGMENT}/")
