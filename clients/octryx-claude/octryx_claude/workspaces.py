"""``--workspace`` takes a Workspace id or a case-insensitive exact name from the user's Workspaces.
When the list cannot be read, a valid id is still used (the platform authorizes every call)."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .platform import CONTROL_PLANE_PREFIX, valid_header_value
from .state import LocalState
from .tokens import GATEWAY_AUDIENCE, TokenUnavailableError, get_access_token

TIMEOUT = 15.0
MAX_LISTED = 20


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str = ""

    def label(self) -> str:
        return f"{self.name} ({self.id})" if self.name else self.id


class WorkspaceError(Exception):
    pass


def fetch_workspaces(state: LocalState, http: httpx.Client, base_url: str) -> list[Workspace] | None:
    try:
        token = get_access_token(state, GATEWAY_AUDIENCE, http=http)
        response = http.get(f"{base_url}{CONTROL_PLANE_PREFIX}/workspaces",
                            headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
        items = response.json().get("items") if response.status_code == 200 else None
    except (httpx.HTTPError, TokenUnavailableError, ValueError, AttributeError):
        return None
    if not isinstance(items, list):
        return None
    return [Workspace(str(item["id"]), str(item.get("name") or "")) for item in items
            if isinstance(item, dict) and isinstance(item.get("id"), str) and valid_header_value(item["id"])]


def _listing(workspaces: list[Workspace]) -> str:
    shown = ", ".join(workspace.label() for workspace in workspaces[:MAX_LISTED])
    more = f" and {len(workspaces) - MAX_LISTED} more" if len(workspaces) > MAX_LISTED else ""
    return (shown + more) or "none"


def resolve_workspace(value: str, workspaces: list[Workspace] | None) -> Workspace:
    text = value.strip()
    if not text:
        raise WorkspaceError("no Workspace given")
    if workspaces is None:
        if valid_header_value(text):
            return Workspace(text)
        raise WorkspaceError(f"cannot resolve the Workspace name {text!r}: the platform did not answer; "
                             "pass the Workspace id")
    for workspace in workspaces:
        if workspace.id == text:
            return workspace
    matches = [workspace for workspace in workspaces if workspace.name.casefold() == text.casefold()]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise WorkspaceError(f"the Workspace name {text!r} is ambiguous; pass the id of one of: {_listing(matches)}")
    raise WorkspaceError(f"unknown Workspace {text!r}; your Workspaces: {_listing(workspaces)}")


def label_for(config: dict, workspace_id: str) -> str:
    name = str(config.get("workspace_name") or "") if config.get("workspace_id") == workspace_id else ""
    return Workspace(workspace_id, name).label()


def resolved_label(state: LocalState, http: httpx.Client, base_url: str, config: dict, workspace_id: str) -> str:
    if config.get("workspace_id") == workspace_id and config.get("workspace_name"):
        return label_for(config, workspace_id)
    for workspace in fetch_workspaces(state, http, base_url) or []:
        if workspace.id == workspace_id:
            return workspace.label()
    return workspace_id


__all__ = ["Workspace", "WorkspaceError", "fetch_workspaces", "label_for", "resolve_workspace", "resolved_label"]
