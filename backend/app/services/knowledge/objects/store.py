"""Immutable, Workspace-partitioned S3-compatible object boundary. Only write-if-absent and a digest-verified read; a
foreign key answers ``not_found``."""

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
    # Swallowed on purpose: a close failure must not replace the state the read already decided.
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
        """The key :meth:`put_if_absent` would address, derived without a request."""
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
            # Diagnostic only: reads always use the configured bucket.
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
