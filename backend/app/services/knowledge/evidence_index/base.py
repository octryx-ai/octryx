"""The one shape every Evidence index client has: run a registered operation for one Workspace.

The operation registry (``operations``) is the closed vocabulary of the Evidence slice: the
projector, the embedding step, the ACL marker convergence and the query store all speak it, and none
of them sees the statements behind it. :class:`~.postgres_client.PostgresEvidenceIndexClient` serves
it from shared PostgreSQL tables keyed by Workspace. Callers type-check against this base, so a
second shape cannot be slipped in by duck typing.
"""

from __future__ import annotations

from typing import Any

from ..identity.workspace import WorkspaceId


class EvidenceIndexClient:
    """Base of the clients that serve the Evidence operation registry."""

    async def run(
        self,
        workspace: WorkspaceId,
        operation_key: str,
        parameters: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        raise NotImplementedError

    async def vectors_available(self) -> bool:
        """Whether the index can hold vectors (the vector mode is unavailable otherwise)."""
        raise NotImplementedError


__all__ = ["EvidenceIndexClient"]
