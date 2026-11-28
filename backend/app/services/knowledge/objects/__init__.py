"""Immutable S3-compatible object boundary for Workspace Knowledge sources. Internal only: no credential, endpoint,
bucket, key or S3 error body leaves this package."""

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
from .inventory import MAX_INVENTORY_PAGE_KEYS, InventoryObject, InventoryPage
from .keys import (
    content_digest_from_key,
    is_key_inside_workspace,
    workspace_object_key,
    workspace_object_prefix,
)
from .maintenance import KnowledgeObjectMaintenance
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
