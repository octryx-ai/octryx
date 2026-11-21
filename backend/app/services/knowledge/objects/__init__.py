"""Immutable S3-compatible object boundary for Workspace Knowledge sources.

Sole owner of the explicit object-store configuration, the content-addressed
Workspace-partitioned key derivation, and the write-if-absent / verify-on-read
operations. Internal only: nothing here is an agent tool, an MCP capability, or
an API surface, and no credential, endpoint, bucket, key, or S3 error body
crosses this package boundary.

Two capabilities with two different owners and two different privilege sets:

- :class:`KnowledgeObjectStore` — the immutable ingestion/retrieval path
  (``PutObject`` + ``GetObject``), wired into ``EvidenceRuntime``;
- :class:`KnowledgeObjectMaintenance` — the operator-owned reconciliation and retention
  capability (``ListObjectsV2`` bounded to one Workspace prefix +
  ``DeleteObject`` of one derived key), constructed only by
  ``services/knowledge_retention`` and never by the runtime.

There is no filesystem code path: an absent or invalid configuration is a typed
state, never a host directory.
"""

from .config import (
    ENV_BUCKET,
    ENV_ENDPOINT_URL,
    ENV_PREFIX,
    ENV_REGION,
    ENV_TIMEOUT_SECONDS,
    KnowledgeObjectStoreConfig,
    object_store_config_from_mapping,
)
from .errors import (
    KnowledgeObjectContractError,
    KnowledgeObjectError,
    KnowledgeObjectIntegrityError,
    KnowledgeObjectInvalidConfigurationError,
    KnowledgeObjectNotConfiguredError,
    KnowledgeObjectNotFoundError,
    KnowledgeObjectOperation,
    KnowledgeObjectOutsidePartitionError,
    KnowledgeObjectState,
    KnowledgeObjectTooLargeError,
    KnowledgeObjectUnauthorizedError,
    KnowledgeObjectUnavailableError,
)
from .keys import (
    content_digest_from_key,
    is_key_inside_workspace,
    workspace_object_key,
    workspace_object_prefix,
)
from .maintenance import (
    MAX_INVENTORY_PAGE_KEYS,
    InventoryObject,
    InventoryPage,
    KnowledgeObjectMaintenance,
)
from .store import MAX_OBJECT_BYTES, KnowledgeObjectStore, StoredObject, content_digest

__all__ = [
    "ENV_BUCKET",
    "ENV_ENDPOINT_URL",
    "ENV_PREFIX",
    "ENV_REGION",
    "ENV_TIMEOUT_SECONDS",
    "MAX_INVENTORY_PAGE_KEYS",
    "MAX_OBJECT_BYTES",
    "InventoryObject",
    "InventoryPage",
    "KnowledgeObjectContractError",
    "KnowledgeObjectError",
    "KnowledgeObjectIntegrityError",
    "KnowledgeObjectMaintenance",
    "KnowledgeObjectInvalidConfigurationError",
    "KnowledgeObjectNotConfiguredError",
    "KnowledgeObjectNotFoundError",
    "KnowledgeObjectOperation",
    "KnowledgeObjectOutsidePartitionError",
    "KnowledgeObjectState",
    "KnowledgeObjectStore",
    "KnowledgeObjectStoreConfig",
    "KnowledgeObjectTooLargeError",
    "KnowledgeObjectUnauthorizedError",
    "KnowledgeObjectUnavailableError",
    "StoredObject",
    "content_digest",
    "content_digest_from_key",
    "is_key_inside_workspace",
    "object_store_config_from_mapping",
    "workspace_object_key",
    "workspace_object_prefix",
]
