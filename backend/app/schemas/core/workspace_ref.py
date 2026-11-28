"""A Workspace (project) id as a request accepts it: one contract for every body field."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BeforeValidator, StringConstraints


def _blank_to_none(value: Any) -> Any:
    return None if isinstance(value, str) and not value.strip() else value


OptionalWorkspaceId = Annotated[str | None, BeforeValidator(_blank_to_none)]
WorkspaceId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

__all__ = ["OptionalWorkspaceId", "WorkspaceId"]
