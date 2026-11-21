"""Modes, sources, states and the result type of Agent Definition resolution.

The resolution logic lives in :mod:`app.services.agent_definition_execution`; see its
docstring for what each mode and state means.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

AGENT_DEFINITION_EXECUTION_MODE_KEY = "agent_definition_execution_mode"

EXECUTION_MODE_PUBLISHED = "published"
EXECUTION_MODE_DRAFT = "draft"
EXECUTION_MODES = frozenset({EXECUTION_MODE_PUBLISHED, EXECUTION_MODE_DRAFT})
#: The authoring default for the *absent* key: saved definitions run as saved.
#: A key set to an unknown value is refused instead.
EXECUTION_MODE_DEFAULT = EXECUTION_MODE_DRAFT
#: Reported instead of the configured value when that value names no known mode.
#: The raw value is admin-authored free text and is never echoed into a response,
#: a trace, or an audit record.
EXECUTION_MODE_UNKNOWN = "unknown"

SOURCE_PUBLISHED_REVISION = "published_revision"
SOURCE_LIVE_DRAFT_ROW = "live_draft_row"

STATUS_RESOLVED = "resolved"
STATUS_NOT_FOUND = "not_found"
STATUS_NEEDS_PUBLICATION = "needs_publication"
STATUS_NEEDS_CONFIGURATION = "needs_configuration"
STATUS_INACTIVE = "inactive"

#: Explicit states that refuse execution on every path, background included.
REFUSAL_STATUSES = frozenset({STATUS_NEEDS_PUBLICATION, STATUS_NEEDS_CONFIGURATION, STATUS_INACTIVE})

#: Typed client-facing code for a definition that published mode cannot execute.
NOT_PUBLISHED_ERROR_CODE = "agent_definition_not_published"
#: Typed client-facing code for a mode key that names no known mode.
NOT_CONFIGURED_ERROR_CODE = "agent_definition_execution_mode_not_configured"
#: Typed client-facing code for a definition that is currently deactivated.
INACTIVE_ERROR_CODE = "agent_definition_inactive"

REFUSAL_CODES: dict[str, str] = {
    STATUS_NEEDS_PUBLICATION: NOT_PUBLISHED_ERROR_CODE,
    STATUS_NEEDS_CONFIGURATION: NOT_CONFIGURED_ERROR_CODE,
    STATUS_INACTIVE: INACTIVE_ERROR_CODE,
}

#: The one canonical metadata key for a resolution. Chat sessions, scheduler task
#: runs, and the turn trace all record provenance under it, so the executed source
#: survives the turn instead of living only in the in-memory payload.
RESOLUTION_METADATA_KEY = "agent_definition_resolution"

PAYLOAD_MODE_KEY = "agentDefinitionResolutionMode"
PAYLOAD_SOURCE_KEY = "agentDefinitionSource"
PAYLOAD_REVISION_ID_KEY = "agentDefinitionRevisionId"
PAYLOAD_REVISION_NUMBER_KEY = "agentDefinitionRevisionNumber"


@dataclass(frozen=True, slots=True)
class AgentDefinitionResolution:
    """The explicit result of resolving one definition for execution."""

    definition_id: str
    mode: str
    status: str
    source: str | None = None
    revision_id: str | None = None
    revision_number: int | None = None
    checksum: str | None = None
    payload: dict[str, Any] | None = None

    @property
    def resolved(self) -> bool:
        return self.status == STATUS_RESOLVED and self.payload is not None

    @property
    def project_id(self) -> str:
        return str((self.payload or {}).get("projectId") or "")

    @property
    def runtime_target_id(self) -> str:
        return str((self.payload or {}).get("runtimeTargetId") or "")

    @property
    def thinking_level(self) -> str:
        return str((self.payload or {}).get("thinkingLevel") or "")

    @property
    def agent_type(self) -> str:
        return str((self.payload or {}).get("agentType") or "")

    def as_metadata(self) -> dict[str, Any]:
        """Audit/trace metadata. Identifiers and states only, no authored content."""
        return {
            "definition_id": self.definition_id,
            "mode": self.mode,
            "status": self.status,
            "source": self.source,
            "revision_id": self.revision_id,
            "revision_number": self.revision_number,
            "checksum": self.checksum,
        }


class AgentDefinitionExecutionModeError(RuntimeError):
    """The mode key is set to a value that names no known mode.

    Raised instead of returning a default, so no caller can accidentally treat a
    misconfigured platform as one running in draft mode. The offending value is
    deliberately not carried on the exception: it is admin-authored free text.
    """

    code = NOT_CONFIGURED_ERROR_CODE

    def __init__(self) -> None:
        super().__init__(
            f"{AGENT_DEFINITION_EXECUTION_MODE_KEY} names no known execution mode"
        )
