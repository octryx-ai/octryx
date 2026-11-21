"""Operator-owned inventory of one Workspace's Knowledge objects.

Why this is a separate class and not one more method on
:class:`~.store.KnowledgeObjectStore`: the store is the immutable path the agent runtime
reaches through ``EvidenceRuntime``, and it must keep needing exactly ``PutObject`` and
``GetObject``. This capability is constructed only by the retention reconciliation, which no
route, tool, MCP capability, prompt or loop imports.

**Exactly one S3 action, narrowed.** ``ListObjectsV2`` is always sent with ``Prefix`` set to
*one* Workspace's derived key prefix and a bounded ``MaxKeys``. There is no bucket-wide list, no
delimiter listing of other prefixes, and no way to pass a caller-supplied prefix: it is derived
from the validated :class:`WorkspaceId` exactly like a write key is.

Least-privilege identity. The operator identity that runs this capability needs
``s3:ListBucket`` restricted by an ``s3:prefix`` condition — and *not* ``s3:GetObject``:
nothing here ever downloads bytes, so the reconciliation identity cannot read Workspace
content at all. Credentials are
resolved by boto3 from the process it runs in and never enter a product object, so the
identity is chosen by deployment, not by configuration this code carries.

What is deliberately absent: no ``HeadObject``, no delete, no lifecycle or
bucket API, no overwrite, no copy, no presign.

Nothing read from the server is retained beyond narrow, validated facts: a derived key, its
content address, an integer size and a timestamp. A key that is not the product's
derivation is **counted, never returned**, so no foreign text can travel out of this module.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from ..identity.workspace import WorkspaceId
from ..retrieval.errors import InvalidWorkspaceError
from .config import KnowledgeObjectStoreConfig
from .errors import (
    KnowledgeObjectContractError,
    KnowledgeObjectError,
    KnowledgeObjectInvalidConfigurationError,
    KnowledgeObjectOperation,
)
from .inventory import (
    _CURSOR,
    _LIST,
    MAX_INVENTORY_BYTE_SIZE,
    MAX_INVENTORY_PAGE_KEYS,
    InventoryObject,
    InventoryPage,
)
from .keys import content_digest_from_key, is_key_inside_workspace, workspace_object_prefix
from .transport import build_s3_client, mapped_error

logger = logging.getLogger(__name__)


class KnowledgeObjectMaintenance:
    """Workspace-scoped inventory. Operator-owned; never a tool."""

    def __init__(self, config: KnowledgeObjectStoreConfig, *, client: Any | None = None) -> None:
        if type(config) is not KnowledgeObjectStoreConfig:
            raise KnowledgeObjectInvalidConfigurationError(KnowledgeObjectOperation.CONFIGURATION)
        self._config = config
        self._client = client
        self._client_lock = asyncio.Lock()

    def __repr__(self) -> str:
        return f"KnowledgeObjectMaintenance(bucket={self._config.bucket!r})"

    @property
    def bucket(self) -> str:
        """The configured bucket, so a caller can compare a persisted reference to it."""
        return self._config.bucket

    def workspace_key_prefix(self, workspace: WorkspaceId) -> str:
        """The derived prefix that bounds one Workspace, with its trailing separator."""
        return f"{workspace_object_prefix(self._config.prefix, self._validated(workspace))}/"

    async def list_workspace(
        self,
        workspace: WorkspaceId,
        *,
        after_key: str | None = None,
        limit: int = MAX_INVENTORY_PAGE_KEYS,
    ) -> InventoryPage:
        """List one bounded page of exactly this Workspace's objects."""
        workspace = self._validated(workspace)
        if type(limit) is not int or not 0 < limit <= MAX_INVENTORY_PAGE_KEYS:
            raise KnowledgeObjectContractError(_LIST)
        prefix = self.workspace_key_prefix(workspace)
        if after_key is not None and (
            type(after_key) is not str or not after_key.startswith(prefix) or not _CURSOR.fullmatch(after_key)
        ):
            # A cursor can only ever be a key this module returned itself.
            raise KnowledgeObjectContractError(_LIST)
        response = await self._list(prefix, after_key, limit)
        return self._page(response, workspace, prefix)

    def _validated(self, workspace: object) -> WorkspaceId:
        if type(workspace) is not WorkspaceId:
            raise InvalidWorkspaceError()
        # Revalidated private copy: a later mutation of the caller's object never applies.
        return WorkspaceId.parse(workspace)

    async def _s3(self) -> Any:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                self._client = await asyncio.to_thread(build_s3_client, self._config)
        return self._client

    async def _list(self, prefix: str, after_key: str | None, limit: int) -> dict:
        client = await self._s3()
        arguments: dict[str, Any] = {
            "Bucket": self._config.bucket,
            "Prefix": prefix,
            "MaxKeys": limit,
        }
        if after_key is not None:
            # StartAfter, not a server continuation token: the cursor stays a key this
            # module derived and validated, so nothing opaque is carried between pages.
            arguments["StartAfter"] = after_key
        failure: KnowledgeObjectError | None = None
        response: Any = None
        try:
            response = await asyncio.to_thread(client.list_objects_v2, **arguments)
        # Every transport exception is reduced to a fixed state below.
        except Exception as error:
            failure = mapped_error(error, _LIST)
        if failure is not None:
            raise failure
        if not isinstance(response, dict):
            raise KnowledgeObjectContractError(_LIST)
        return response

    def _page(self, response: dict, workspace: WorkspaceId, prefix: str) -> InventoryPage:
        """Turn one ``ListObjectsV2`` answer into validated facts, dropping the rest."""
        contents = response.get("Contents")
        if contents is None:
            contents = []
        if not isinstance(contents, list):
            raise KnowledgeObjectContractError(_LIST)
        objects: list[InventoryObject] = []
        unrecognized = 0
        last_key: str | None = None
        for entry in contents:
            key = entry.get("Key") if isinstance(entry, dict) else None
            if type(key) is not str or not key.startswith(prefix):
                # The server ignored the prefix, or answered something that is not an
                # object entry: neither may influence the inventory of this Workspace.
                unrecognized += 1
                continue
            if _CURSOR.fullmatch(key):
                last_key = key
            candidate = self._inventory_object(key, entry, workspace)
            if candidate is None:
                unrecognized += 1
                continue
            objects.append(candidate)
        truncated = response.get("IsTruncated") is True
        if unrecognized:
            logger.warning(
                "Knowledge object inventory saw %d unrecognized keys: workspace=%s",
                unrecognized,
                workspace.canonical,
            )
        return InventoryPage(
            objects=tuple(objects),
            unrecognized_count=unrecognized,
            truncated=truncated,
            next_after_key=last_key if truncated else None,
        )

    def _inventory_object(self, key: str, entry: dict, workspace: WorkspaceId) -> InventoryObject | None:
        """One validated entry, or ``None`` when it is not a product-derived object."""
        digest = content_digest_from_key(key)
        if digest is None or not is_key_inside_workspace(key, self._config.prefix, workspace):
            return None
        size = entry.get("Size")
        modified = entry.get("LastModified")
        if type(size) is not int or not 0 <= size <= MAX_INVENTORY_BYTE_SIZE:
            return None
        if not isinstance(modified, datetime):
            # Without a write time the object's age is unknown, so it must never become a
            # deletion candidate.
            return None
        # One convention crosses this boundary: naive UTC. An aware server value is converted,
        # a naive one is taken as UTC, which is what every timestamp in this codebase is.
        naive = modified.astimezone(UTC).replace(tzinfo=None) if modified.tzinfo else modified
        return InventoryObject(key=key, content_sha256=digest, byte_size=size, last_modified=naive)
