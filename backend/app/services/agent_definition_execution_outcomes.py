"""What each kind of caller does with an Agent Definition resolution. Kept together so no caller quietly grows a
fallback."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from .agent_definition_execution_states import (
    PAYLOAD_MODE_KEY,
    PAYLOAD_REVISION_ID_KEY,
    PAYLOAD_REVISION_NUMBER_KEY,
    PAYLOAD_SOURCE_KEY,
    REFUSAL_CODES,
    REFUSAL_STATUSES,
    RESOLUTION_METADATA_KEY,
    STATUS_INACTIVE,
    STATUS_NEEDS_CONFIGURATION,
    STATUS_NEEDS_PUBLICATION,
    STATUS_NOT_FOUND,
    AgentDefinitionResolution,
)


class AgentDefinitionExecutionError(RuntimeError):
    # Built from a typed code and identifiers only, so it is safe to persist in ``task_run.error`` and step logs.

    def __init__(self, resolution: AgentDefinitionResolution) -> None:
        self.resolution = resolution
        self.code = REFUSAL_CODES.get(resolution.status, resolution.status)
        super().__init__(
            f"{self.code} definition={resolution.definition_id or '-'} "
            f"mode={resolution.mode}"
        )

    def as_metadata(self) -> dict[str, Any]:
        return {"code": self.code, **self.resolution.as_metadata()}


def require_execution_payload(resolution: AgentDefinitionResolution) -> dict[str, Any]:
    if resolution.status in REFUSAL_STATUSES:
        raise HTTPException(status_code=409, detail=execution_refusal_detail(resolution))
    if resolution.status == STATUS_NOT_FOUND or resolution.payload is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return resolution.payload


def execution_payload_or_none(
    resolution: AgentDefinitionResolution,
) -> dict[str, Any] | None:
    # A refusal is not collapsed into ``None``: downgrading a refused agent to no agent would be a hidden fallback.
    if resolution.status in REFUSAL_STATUSES:
        raise HTTPException(status_code=409, detail=execution_refusal_detail(resolution))
    return resolution.payload


def require_background_execution_payload(
    resolution: AgentDefinitionResolution,
    *,
    logger_: logging.Logger,
    subject: str,
) -> dict[str, Any] | None:
    # A refused definition fails the run instead of running an agent-less turn; only an id that resolves to nothing runs
    # without one.
    if resolution.status in REFUSAL_STATUSES:
        error = AgentDefinitionExecutionError(resolution)
        logger_.error(
            "[%s] refusing background execution: %s (definition=%s mode=%s)",
            subject,
            error.code,
            resolution.definition_id,
            resolution.mode,
        )
        raise error
    if resolution.status == STATUS_NOT_FOUND:
        logger_.warning(
            "[%s] agent_definition %s not found", subject, resolution.definition_id
        )
        return None
    return resolution.payload


def resolution_metadata(resolution: AgentDefinitionResolution) -> dict[str, Any]:
    return {RESOLUTION_METADATA_KEY: resolution.as_metadata()}


def payload_resolution_metadata(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    return {
        RESOLUTION_METADATA_KEY: {
            "mode": str(payload.get(PAYLOAD_MODE_KEY) or ""),
            "source": str(payload.get(PAYLOAD_SOURCE_KEY) or ""),
            "revision_id": payload.get(PAYLOAD_REVISION_ID_KEY) or None,
            "revision_number": payload.get(PAYLOAD_REVISION_NUMBER_KEY) or None,
        }
    }


def execution_refusal_detail(resolution: AgentDefinitionResolution) -> dict[str, Any]:
    messages = {
        STATUS_NEEDS_PUBLICATION: (
            "This agent definition has no published revision and "
            "agent_definition_execution_mode is 'published'."
        ),
        STATUS_NEEDS_CONFIGURATION: (
            "agent_definition_execution_mode is set to a value that is not "
            "'published' or 'draft'."
        ),
        STATUS_INACTIVE: (
            "This agent is inactive, so it cannot start new turns. "
            "Activate it on its agent page to use it again."
        ),
    }
    return {
        "code": REFUSAL_CODES.get(resolution.status, resolution.status),
        "message": messages.get(resolution.status, ""),
        "definition_id": resolution.definition_id,
    }

__all__ = [
    "AgentDefinitionExecutionError",
    "execution_payload_or_none",
    "execution_refusal_detail",
    "payload_resolution_metadata",
    "require_background_execution_payload",
    "require_execution_payload",
    "resolution_metadata",
]
