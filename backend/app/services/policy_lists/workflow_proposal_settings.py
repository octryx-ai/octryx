"""Platform settings of workflow proposals as an admin-edited governed record."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .errors import INVALID_ENTRY, INVALID_PAYLOAD, OUT_OF_RANGE, PolicyListError
from .records import PolicyListSpec, read_policy_list_state

TIMEOUT_SECONDS_FIELD = "timeout_seconds"
SETTINGS_FIELDS = (TIMEOUT_SECONDS_FIELD,)
TIMEOUT_SECONDS_MIN = 1
TIMEOUT_SECONDS_MAX = 60
SEED_TIMEOUT_SECONDS = 10


@dataclass(frozen=True, slots=True)
class WorkflowProposalSettings:
    timeout_seconds: int = SEED_TIMEOUT_SECONDS


def _seed() -> dict[str, Any]:
    return {TIMEOUT_SECONDS_FIELD: SEED_TIMEOUT_SECONDS}


def _is_timeout(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and TIMEOUT_SECONDS_MIN <= value <= TIMEOUT_SECONDS_MAX
    )


def _read(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != set(SETTINGS_FIELDS):
        raise ValueError("settings")
    if not _is_timeout(raw[TIMEOUT_SECONDS_FIELD]):
        raise ValueError(TIMEOUT_SECONDS_FIELD)
    return {field: raw[field] for field in SETTINGS_FIELDS}


WORKFLOW_PROPOSAL_SETTINGS_SPEC = PolicyListSpec(
    list_id="workflow_proposal_settings",
    config_key="policy.workflow_proposal_settings",
    key_prefix="workflow_proposal_settings",
    title="Workflow proposal settings",
    description="timeout_seconds: how long the proposal model call may take (1-60).",
    seed_values=_seed,
    read_values=_read,
)


def validate_workflow_proposal_settings(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise PolicyListError(INVALID_PAYLOAD, "values must be an object of the proposal settings.")
    unknown = sorted(str(field) for field in raw if field not in SETTINGS_FIELDS)
    missing = sorted(field for field in SETTINGS_FIELDS if field not in raw)
    if unknown or missing:
        message = "values must name exactly the fields " + ", ".join(SETTINGS_FIELDS) + "."
        raise PolicyListError(INVALID_PAYLOAD, message, unknown + missing)
    timeout = raw[TIMEOUT_SECONDS_FIELD]
    if not isinstance(timeout, int) or isinstance(timeout, bool):
        raise PolicyListError(INVALID_ENTRY, "timeout_seconds is a whole number of seconds.", [TIMEOUT_SECONDS_FIELD])
    if not _is_timeout(timeout):
        raise PolicyListError(
            OUT_OF_RANGE,
            f"timeout_seconds is between {TIMEOUT_SECONDS_MIN} and {TIMEOUT_SECONDS_MAX}.",
            [TIMEOUT_SECONDS_FIELD],
        )
    return {TIMEOUT_SECONDS_FIELD: timeout}


async def read_workflow_proposal_settings(db: AsyncSession) -> WorkflowProposalSettings:
    values = (await read_policy_list_state(db, WORKFLOW_PROPOSAL_SETTINGS_SPEC)).values
    return WorkflowProposalSettings(timeout_seconds=int(values[TIMEOUT_SECONDS_FIELD]))


__all__ = [
    "SEED_TIMEOUT_SECONDS",
    "TIMEOUT_SECONDS_FIELD",
    "WORKFLOW_PROPOSAL_SETTINGS_SPEC",
    "WorkflowProposalSettings",
    "read_workflow_proposal_settings",
    "validate_workflow_proposal_settings",
]
