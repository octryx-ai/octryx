"""The one shape every Evidence index client has: run a registered operation for one Workspace."""

from __future__ import annotations

from typing import Any

from ..identity.workspace import WorkspaceId


class EvidenceIndexClient:
    async def run(
        self,
        workspace: WorkspaceId,
        operation_key: str,
        parameters: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        raise NotImplementedError

    async def vectors_available(self) -> bool:
        raise NotImplementedError


__all__ = ["EvidenceIndexClient"]
