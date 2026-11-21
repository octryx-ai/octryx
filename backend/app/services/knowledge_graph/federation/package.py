"""The entity-graph package format, its signature and its verification."""

from __future__ import annotations

from typing import Any

from ...engineering_knowledge import (
    sign_engineering_knowledge_package,
    verify_engineering_knowledge_package_signature,
)

ENTITY_GRAPH_PACKAGE_FORMAT = "entity-graph-package/v1"
FEDERATED_TRUST_LEVEL = "federated"
MAX_EXPORT_NODES = 5000


class EntityGraphPackageError(ValueError):
    """Raised when an entity-graph package is malformed or fails verification."""


def _node_ref(node_type: str, node_key: str) -> str:
    return f"{node_type}:{node_key}"


def sign_entity_graph_package(
    package: dict[str, Any], *, signing_key: str, signing_key_id: str = "local-dev"
) -> dict[str, Any]:
    return sign_engineering_knowledge_package(
        package, signing_key=signing_key, signing_key_id=signing_key_id
    )


def verify_entity_graph_package(package: dict[str, Any], *, signing_key: str) -> None:
    """Raise ``EntityGraphPackageError`` unless the package is well-formed and
    carries a valid signature."""
    if not isinstance(package, dict) or package.get("format") != ENTITY_GRAPH_PACKAGE_FORMAT:
        raise EntityGraphPackageError(f"Unsupported package format: {package.get('format')!r}")
    result = verify_engineering_knowledge_package_signature(package, signing_key=signing_key)
    if not result.get("valid"):
        raise EntityGraphPackageError(f"Package signature invalid: {result.get('reason') or 'mismatch'}")
