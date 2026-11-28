"""The details of an audit record as readers see them: only values from its writer's fixed vocabulary, and counts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...models.project.knowledge_evidence import ALL_OUTBOX_STATES
from ...models.runtime.mcp_server import MCP_OWNER_PLATFORM, MCP_OWNER_WORKSPACE
from ...models.security.compliance_audit import (
    AUDIT_ADMIN_CHANGE,
    AUDIT_CONNECTOR_ACCESS,
    AUDIT_RUNTIME_ACTION,
    ComplianceAuditRecord,
)
from ..knowledge.projection.recovery_vocabulary import (
    ALL_RECOVERY_OPERATIONS,
    ALL_RECOVERY_RESULTS,
)
from ..knowledge.projection.recovery_vocabulary import (
    AUDIT_RESOURCE_TYPE as PROJECTION_RECOVERY_RESOURCE,
)
from ..mcp_audit_vocabulary import ALL_ACTIONS as MCP_ACTIONS
from ..mcp_audit_vocabulary import RESOURCE_TYPE as MCP_REGISTRATION_RESOURCE
from .redaction import is_credential_value

_MAX_COUNT = 1_000_000_000


def _one_of(vocabulary: frozenset[str] | set[str]) -> Callable[[Any], bool]:
    return lambda value: isinstance(value, str) and value in vocabulary


def _count(value: Any) -> bool:
    return type(value) is int and 0 <= value <= _MAX_COUNT


_MCP_REGISTRATION = {
    "action": _one_of(MCP_ACTIONS),
    "owner_scope": _one_of({MCP_OWNER_PLATFORM, MCP_OWNER_WORKSPACE}),
    "revision": _count,
    "credential_binding_count": _count,
}
_PROJECTION_RECOVERY = {
    "operation": _one_of(ALL_RECOVERY_OPERATIONS),
    "previous_state": _one_of(ALL_OUTBOX_STATES),
    "result": _one_of(ALL_RECOVERY_RESULTS),
}

SAFE_FIELDS: dict[tuple[str, str], dict[str, Callable[[Any], bool]]] = {
    (AUDIT_ADMIN_CHANGE, MCP_REGISTRATION_RESOURCE): _MCP_REGISTRATION,
    (AUDIT_CONNECTOR_ACCESS, MCP_REGISTRATION_RESOURCE): _MCP_REGISTRATION,
    (AUDIT_RUNTIME_ACTION, PROJECTION_RECOVERY_RESOURCE): _PROJECTION_RECOVERY,
}


def _shown(record: ComplianceAuditRecord, key: str, value: Any) -> bool:
    check = SAFE_FIELDS.get((record.event_type, record.resource_type), {}).get(key)
    if check is None or not check(value) or is_credential_value(value):
        return False
    # A record flagged sensitive keeps only vocabulary values: a number there has no known origin.
    return not (record.contains_sensitive and check is _count)


def project_details(record: ComplianceAuditRecord) -> tuple[dict[str, Any], int]:
    details = record.details if isinstance(record.details, dict) else {}
    shown = {key: value for key, value in details.items() if _shown(record, key, value)}
    return shown, len(details) - len(shown)
