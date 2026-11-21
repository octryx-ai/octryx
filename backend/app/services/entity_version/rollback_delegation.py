"""Explicit rollback ownership for entity types that have a dedicated revision API.

The generic ``EntityVersion`` path keeps recording audit snapshots for every
supported entity type, and listing those snapshots stays unchanged. *Restoring*
one of them is a different thing: it is a governed write onto a live aggregate.
Where an aggregate owns a fail-closed revision boundary, that boundary is the
only writer allowed to perform the restore — the generic path would otherwise
reapply a raw snapshot with no validation, no Workspace authorization of the
target scope, and no revision lineage.

This is an explicit, service-owned state rather than a string check in the
route: the transport calls one assertion, the assertion consults
``ROLLBACK_DELEGATIONS``, and the caller receives a stable machine-readable
conflict naming the API that does own the restore.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException

#: A conflict, not 400 or 404: the request is well-formed and the entity may
#: exist, but the generic path is not the writer that owns its restore.
ROLLBACK_DELEGATED_STATUS = 409

#: Stable error code clients may branch on; the human message may be reworded.
ROLLBACK_DELEGATED_CODE = "rollback_owned_by_dedicated_revision_api"


@dataclass(frozen=True, slots=True)
class RollbackDelegation:
    """One entity type whose restore is owned by a dedicated revision API."""

    entity_type: str
    dedicated_api: str
    reason: str

    def as_detail(self) -> dict[str, str]:
        return {
            "code": ROLLBACK_DELEGATED_CODE,
            "entity_type": self.entity_type,
            "dedicated_api": self.dedicated_api,
            "message": self.reason,
        }


ROLLBACK_DELEGATIONS: dict[str, RollbackDelegation] = {
    "agent_definitions": RollbackDelegation(
        entity_type="agent_definitions",
        dedicated_api="POST /api/v1/agent-definitions/revisions/{revision_id}/restore",
        reason=(
            "Agent definitions are restored through their immutable revision API, "
            "which re-validates the snapshot and authorizes the target Workspace."
        ),
    ),
}


def rollback_delegation_for(entity_type: str) -> RollbackDelegation | None:
    """Return the delegation for *entity_type*, or ``None`` when it restores here."""
    return ROLLBACK_DELEGATIONS.get(entity_type)


def assert_rollback_not_delegated(entity_type: str) -> None:
    """Raise the stable conflict when *entity_type* is restored elsewhere.

    Called before the generic path reads a version row or touches a live row, so
    a delegated entity type can never be mutated here and the answer does not
    depend on whether the requested version happens to exist.
    """
    delegation = rollback_delegation_for(entity_type)
    if delegation is None:
        return
    raise HTTPException(
        status_code=ROLLBACK_DELEGATED_STATUS, detail=delegation.as_detail()
    )


__all__ = [
    "ROLLBACK_DELEGATED_CODE",
    "ROLLBACK_DELEGATED_STATUS",
    "ROLLBACK_DELEGATIONS",
    "RollbackDelegation",
    "assert_rollback_not_delegated",
    "rollback_delegation_for",
]
