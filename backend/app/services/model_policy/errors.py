"""Explicit refusals of the Model Policy registry.

Every refusal carries a stable ``code`` (asserted by tests and read by the UI)
and the HTTP status the transport renders it with. ``facts`` holds only
identifiers and closed-vocabulary values the caller already knows; it never
echoes document content, approval reasons, or exception text.
"""

from __future__ import annotations

from typing import Any

# Lookup
MODEL_POLICY_NOT_FOUND = "model_policy_not_found"
REVISION_NOT_FOUND = "revision_not_found"

# Authoring
NAME_INVALID = "name_invalid"
NAME_TAKEN = "name_taken"
REGISTRY_ENTRY_RETIRED = "registry_entry_retired"
REGISTRY_ENTRY_ALREADY_RETIRED = "registry_entry_already_retired"
MODEL_POLICY_ENTRIES_INVALID = "model_policy_entries_invalid"

# Lifecycle
REVISION_NOT_DRAFT = "revision_not_draft"
REVISION_NOT_IN_REVIEW = "revision_not_in_review"
REVISION_ALREADY_RETIRED = "revision_already_retired"
DIGEST_CHANGED = "digest_changed"
APPROVAL_REQUIRED = "governance_approval_required"
APPROVAL_REFUSED = "governance_approval_refused"
MODEL_POLICY_NEEDS_CONFIGURATION = "needs_configuration"

_HTTP_STATUS: dict[str, int] = {
    MODEL_POLICY_NOT_FOUND: 404,
    REVISION_NOT_FOUND: 404,
    NAME_INVALID: 422,
    NAME_TAKEN: 409,
    REGISTRY_ENTRY_RETIRED: 409,
    REGISTRY_ENTRY_ALREADY_RETIRED: 409,
    MODEL_POLICY_ENTRIES_INVALID: 422,
    REVISION_NOT_DRAFT: 409,
    REVISION_NOT_IN_REVIEW: 409,
    REVISION_ALREADY_RETIRED: 409,
    DIGEST_CHANGED: 409,
    APPROVAL_REQUIRED: 409,
    APPROVAL_REFUSED: 409,
    MODEL_POLICY_NEEDS_CONFIGURATION: 409,
}


class RegistryRefusalError(Exception):
    """An explicit, coded refusal of a registry operation."""

    def __init__(self, code: str, **facts: Any) -> None:
        super().__init__(code)
        self.code = code
        self.facts = facts

    @property
    def http_status(self) -> int:
        return _HTTP_STATUS.get(self.code, 409)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, **self.facts}


__all__ = [name for name in dir() if name.isupper()] + ["RegistryRefusalError"]
