"""Content-addressed, Workspace-partitioned object keys: ``<prefix>/knowledge/octryx_ws_<32 hex>/sha256/<aa>/<bb>/<64
hex>``. Nothing user-supplied is part of a key."""

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
    """The content address ``key`` encodes, or ``None`` when it is not a derived key."""
    if type(key) is not str or not _OBJECT_KEY.fullmatch(key):
        return None
    digest = key.rsplit("/", 1)[-1]
    if not key.endswith(f"/{DIGEST_SEGMENT}/{digest[0:2]}/{digest[2:4]}/{digest}"):
        return None
    return digest


def is_key_inside_workspace(key: object, prefix: str | None, workspace: WorkspaceId) -> bool:
    """True when ``key`` lies in exactly this Workspace's partition."""
    if type(key) is not str or not _OBJECT_KEY.fullmatch(key):
        return False
    return key.startswith(f"{workspace_object_prefix(prefix, workspace)}/{DIGEST_SEGMENT}/")
