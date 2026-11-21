"""Immutable, Workspace-partitioned S3-compatible object boundary.

The only write is *write-if-absent* at a content-addressed key, and the only
read *verifies the digest* before returning bytes. There is no overwrite, no
delete, no list, no presign, and no filesystem path anywhere in this module, so
a misconfigured deployment cannot degrade into writing Workspace bytes onto the
host.

This class stays closed beside the operator-owned inventory and deletion
capability: ``maintenance.KnowledgeObjectMaintenance`` is a **separate** class with its
own client, is never part of ``EvidenceRuntime``, and nothing in the ingestion, retrieval,
runtime or tool path can reach it. So the identity the API process holds still needs only
``PutObject`` and ``GetObject``.

**Exactly two S3 actions.** ``PutObject`` and ``GetObject``, and nothing else.
Write-if-absent is the ``IfNoneMatch: "*"`` precondition on the write itself, not a
``HeadObject`` probe followed by a write: the probe was a second required privilege
and a second round trip for an answer the write already gives, and its
race window meant two writers could both see "absent". A refused precondition
(412) *is* the "already present" answer. A server that ignores ``IfNoneMatch``
re-writes byte-identical content at the same content address, which is harmless but
unproven against a real endpoint: activating this boundary against a real
S3-compatible server is a separate gate, and the 412 path is one of the three things
that gate has to observe.

Every response body is closed. ``GetObject`` hands back a streaming body that holds
a pooled connection until it is released, so the read closes it in a ``finally``
even when the digest check is about to refuse the bytes.

Isolation: every key is derived from the validated :class:`WorkspaceId`, and a
read first checks that the persisted key lies inside the caller's own partition.
A key belonging to another Workspace answers ``not_found`` like an absent object,
so no probe can confirm that another Workspace holds the same document.

The configured bucket is the only bucket this boundary ever addresses. The bucket a
ledger row recorded is provenance, not an address: every read uses the configured
bucket at the partition-checked key and verifies the digest, whatever bucket the
revision recorded.

Credentials never appear here: boto3 resolves them from its default chain, and
no credential, endpoint, bucket, key, or S3 error body is copied into an error,
a log record, or a return value. Transport failures are mapped to fixed states
and re-raised outside the ``except`` block, so no botocore exception (which
references the signed request) is chained as ``__cause__`` or ``__context__``.

The S3 client is synchronous; calls run in a worker thread and are bounded by
botocore's own connect/read timeouts rather than by ``asyncio.timeout``, because
a cancelled ``to_thread`` would leak the thread rather than the request.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any

from ..identity.workspace import WorkspaceId
from ..retrieval.errors import InvalidWorkspaceError
from .config import KnowledgeObjectStoreConfig
from .errors import (
    KnowledgeObjectContractError,
    KnowledgeObjectError,
    KnowledgeObjectIntegrityError,
    KnowledgeObjectInvalidConfigurationError,
    KnowledgeObjectOperation,
    KnowledgeObjectOutsidePartitionError,
    KnowledgeObjectTooLargeError,
)
from .keys import is_key_inside_workspace, workspace_object_key
from .source_object import SourceObjectRef
from .transport import build_s3_client, error_code, failure_cause, mapped_error

logger = logging.getLogger(__name__)

# Sized for specifications as PDF; text-native uploads keep 8 MiB (ingestion/text_ingest.py).
MAX_OBJECT_BYTES = 32 * 1024 * 1024
STORED_CONTENT_TYPE = "application/octet-stream"

_PUT = KnowledgeObjectOperation.PUT_OBJECT
_GET = KnowledgeObjectOperation.GET_OBJECT

_ALREADY_PRESENT_CODES = frozenset({"412", "PreconditionFailed"})


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Result of one write-if-absent: where the bytes are and whether we wrote them."""

    ref: SourceObjectRef
    byte_size: int
    created: bool

    def __post_init__(self) -> None:
        if type(self.ref) is not SourceObjectRef or self.ref.content_sha256 is None:
            raise KnowledgeObjectContractError(_PUT)
        if type(self.byte_size) is not int or not 0 < self.byte_size <= MAX_OBJECT_BYTES:
            raise KnowledgeObjectContractError(_PUT)
        if type(self.created) is not bool:
            raise KnowledgeObjectContractError(_PUT)


def content_digest(data: bytes) -> str:
    """Lower-case hex SHA-256 of exactly ``bytes``; the address of the object."""
    if type(data) is not bytes:
        raise KnowledgeObjectContractError(_PUT)
    return hashlib.sha256(data).hexdigest()


async def _closed(body: Any) -> None:
    """Release a streaming response body, whatever the read did.

    A failure to close is not the caller's problem and must not replace the state
    the read already decided, so it is swallowed on purpose and nothing from it is
    retained — the connection is dropped by the pool either way.
    """
    close = getattr(body, "close", None)
    if close is None:
        return
    try:
        await asyncio.to_thread(close)
    # Closing must never mask the read's outcome.
    except Exception:
        logger.warning("Knowledge object response body could not be closed")


class KnowledgeObjectStore:
    """Workspace-scoped, immutable object storage. Internal; never a tool."""

    def __init__(self, config: KnowledgeObjectStoreConfig, *, client: Any | None = None) -> None:
        if type(config) is not KnowledgeObjectStoreConfig:
            raise KnowledgeObjectInvalidConfigurationError(KnowledgeObjectOperation.CONFIGURATION)
        self._config = config
        self._client = client
        self._client_lock = asyncio.Lock()

    def __repr__(self) -> str:
        return f"KnowledgeObjectStore(bucket={self._config.bucket!r})"

    def planned_key(self, workspace: WorkspaceId, data: bytes) -> str:
        """The key :meth:`put_if_absent` would address, derived without a request.

        The ingestion boundary needs the key *before* the write, because publishing a
        reference to an object must be serialized against an operator deletion of exactly
        that object, and that boundary is taken before the first byte is written (
        ``services/knowledge/object_publication_lock.py``). Pure derivation: no client is
        built, nothing reaches the wire, and the answer is the same value the write uses.
        """
        workspace = self._validated_workspace(workspace)
        if type(data) is not bytes or not data:
            raise KnowledgeObjectContractError(_PUT)
        if len(data) > MAX_OBJECT_BYTES:
            raise KnowledgeObjectTooLargeError(_PUT)
        return workspace_object_key(self._config.prefix, workspace, content_digest(data))

    async def put_if_absent(self, workspace: WorkspaceId, data: bytes) -> StoredObject:
        """Store ``data`` under its content address unless it is already there."""
        workspace = self._validated_workspace(workspace)
        if type(data) is not bytes or not data:
            raise KnowledgeObjectContractError(_PUT)
        if len(data) > MAX_OBJECT_BYTES:
            raise KnowledgeObjectTooLargeError(_PUT)
        digest = content_digest(data)
        key = workspace_object_key(self._config.prefix, workspace, digest)
        ref = SourceObjectRef(bucket=self._config.bucket, key=key, content_sha256=digest)

        # One call, no presence probe: the precondition on the write is what makes
        # this write-if-absent, and a refused precondition is the "already there"
        # answer. Whether the stored bytes really hash to their address is decided
        # by ``get_verified``, which is the only place that can actually check it.
        created = await self._put_new(key, data, digest)
        logger.info(
            "Knowledge object stored: created=%s workspace=%s bytes=%d",
            created,
            workspace.canonical,
            len(data),
        )
        return StoredObject(ref=ref, byte_size=len(data), created=created)

    async def get_verified(self, workspace: WorkspaceId, ref: SourceObjectRef) -> bytes:
        """Read one object of this Workspace and refuse a digest mismatch."""
        workspace = self._validated_workspace(workspace)
        if type(ref) is not SourceObjectRef or ref.content_sha256 is None:
            raise KnowledgeObjectContractError(_GET)
        # Out of scope reads like absent: no probe confirms another Workspace's object.
        if not is_key_inside_workspace(ref.key, self._config.prefix, workspace):
            raise KnowledgeObjectOutsidePartitionError(_GET)
        if ref.bucket != self._config.bucket:
            # Diagnostic only: reads always use the configured bucket (module docstring).
            logger.info("Knowledge object recorded under another bucket: workspace=%s", workspace.canonical)

        data = await self._get_bounded(ref.key)
        if content_digest(data) != ref.content_sha256:
            logger.warning("Knowledge object digest mismatch: workspace=%s", workspace.canonical)
            raise KnowledgeObjectIntegrityError(_GET)
        return data

    def _validated_workspace(self, workspace: object) -> WorkspaceId:
        if type(workspace) is not WorkspaceId:
            raise InvalidWorkspaceError()
        # Revalidated private copy: a later mutation of the caller's object never applies.
        return WorkspaceId.parse(workspace)

    async def _s3(self) -> Any:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                self._client = await asyncio.to_thread(self._build_client)
        return self._client

    def _build_client(self) -> Any:
        return build_s3_client(self._config)

    async def _put_new(self, key: str, data: bytes, digest: str) -> bool:
        client = await self._s3()
        checksum = base64.b64encode(bytes.fromhex(digest)).decode("ascii")
        failure: KnowledgeObjectError | None = None
        already_present = False
        cause = ""
        started = time.monotonic()
        try:
            await asyncio.to_thread(
                client.put_object,
                Bucket=self._config.bucket,
                Key=key,
                Body=data,
                ContentLength=len(data),
                ContentType=STORED_CONTENT_TYPE,
                # The server verifies the digest it is addressed by, and refuses
                # to replace an object that a concurrent writer already created.
                ChecksumSHA256=checksum,
                IfNoneMatch="*",
            )
        # Every transport exception is reduced to a fixed state below.
        except Exception as error:
            if error_code(error) in _ALREADY_PRESENT_CODES:
                already_present = True
            else:
                failure = mapped_error(error, _PUT)
                cause = failure_cause(error)
        if failure is not None:
            # Fixed facts only: the state, the code or client exception class, the elapsed time.
            logger.warning(
                "Knowledge object write failed: state=%s cause=%s seconds=%.1f",
                failure.state.value,
                cause,
                time.monotonic() - started,
            )
            raise failure
        return not already_present

    async def _get_bounded(self, key: str) -> bytes:
        client = await self._s3()
        failure: KnowledgeObjectError | None = None
        data: bytes | None = None
        body: Any = None
        try:
            response = await asyncio.to_thread(client.get_object, Bucket=self._config.bucket, Key=key)
            body = response.get("Body") if isinstance(response, dict) else None
            if body is None:
                failure = KnowledgeObjectContractError(_GET)
            else:
                # One byte over the bound is read on purpose, so an oversized
                # object is detected without materializing all of it.
                data = await asyncio.to_thread(body.read, MAX_OBJECT_BYTES + 1)
        # Every transport exception is reduced to a fixed state below.
        except Exception as error:
            failure = mapped_error(error, _GET)
        finally:
            # The pooled connection is released here or not at all: an oversized or
            # digest-mismatched object refuses *after* this, and a partially read
            # stream would otherwise keep its connection until it is collected.
            await _closed(body)
        if failure is not None:
            raise failure
        if type(data) is not bytes or not data:
            raise KnowledgeObjectContractError(_GET)
        if len(data) > MAX_OBJECT_BYTES:
            raise KnowledgeObjectTooLargeError(_GET)
        return data
