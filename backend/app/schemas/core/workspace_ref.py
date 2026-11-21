"""A Workspace (project) id as a request accepts it: one contract for every body field.

- **Optional** (``OptionalWorkspaceId``): an empty or blank value means "no Workspace", the same as an absent field
  (and as the query parameters' ``project_id=`` default the chat and the panels send), so it is ``None`` from the
  boundary on and never reaches a row as ``""``.
- **Required** (``WorkspaceId``): a blank value is no Workspace, so the request is refused at the boundary (422).

Whether a non-blank id names an existing Workspace is the route's access check (``access_control``), not this type.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BeforeValidator, StringConstraints


def _blank_to_none(value: Any) -> Any:
    return None if isinstance(value, str) and not value.strip() else value


OptionalWorkspaceId = Annotated[str | None, BeforeValidator(_blank_to_none)]
WorkspaceId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

__all__ = ["OptionalWorkspaceId", "WorkspaceId"]
