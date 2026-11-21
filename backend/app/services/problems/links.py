"""Where a problem is fixed today: the one page per target (problems aggregator).

Every ``fix`` of every collector comes from :func:`fix_link`, so the targets can move in one place. A connection
target opens the connection page: ``/chat?area=admin&tab=adminConnections&connection=<uuid>``, or the
connections list when the problem names no connection (an unlinked use, a connector check without a connection).
The addresses follow the chat shell's URL contract (``/chat?area=<area>&tab=<page>`` plus the page's own focus
parameters, see ``frontend/chat/src``).
"""

from __future__ import annotations

from urllib.parse import urlencode

TARGET_CONNECTION = "connection"
TARGET_PROVIDER = "provider"
TARGET_KNOWLEDGE_SOURCE = "knowledge_source"
TARGET_INTAKE = "intake"
TARGET_SESSION = "session"
TARGET_WORK = "work"
TARGET_TASKS = "tasks"
TARGET_RULE = "rule"
TARGET_DEVICE = "device"
TARGET_BUDGET = "budget"
TARGET_MODEL = "model"


def _href(params: dict[str, str | None]) -> str:
    return "/chat?" + urlencode({key: value for key, value in params.items() if value})


def fix_link(target: str, *, workspace_id: str | None = None, object_id: str | None = None) -> dict[str, str]:
    """``{label, href}`` of the page that fixes a problem about ``object_id`` (in ``workspace_id``)."""
    ws = workspace_id or None
    if target == TARGET_CONNECTION:
        return {"label": "Open the connection" if object_id else "Open connections",
                "href": _href({"area": "admin", "tab": "adminConnections", "connection": object_id})}
    if target == TARGET_PROVIDER:
        return {"label": "Open the model provider",
                "href": _href({"area": "admin", "tab": "providers", "provider": object_id})}
    if target == TARGET_KNOWLEDGE_SOURCE:
        return {"label": "Open the knowledge source",
                "href": _href({"area": "knowledge", "tab": "workspaceKnowledge", "workspace_id": ws,
                               "source": object_id, "source_view": "page"})}
    if target == TARGET_INTAKE:
        return {"label": "Open the ticket intake", "href": _href({"area": "work", "workspace_id": ws,
                                                                  "work_view": "intake"})}
    if target == TARGET_SESSION:
        return {"label": "Open the run", "href": _href({"session_id": object_id, "workspace_id": ws})}
    if target == TARGET_WORK:
        return {"label": "Open the work item" if object_id else "Open Work",
                "href": _href({"area": "work", "workspace_id": ws, "work_item_id": object_id})}
    if target == TARGET_TASKS:
        return {"label": "Open the action", "href": _href({"area": "admin", "tab": "tasks", "task": object_id})}
    if target == TARGET_RULE:
        return {"label": "Show the decisions of this rule",
                "href": _href({"area": "operations", "tab": "observabilityDecisions", "policy": object_id,
                               "outcome": "denied", "workspace_id": ws})}
    if target == TARGET_DEVICE:
        return {"label": "Open devices", "href": _href({"area": "personal", "tab": "devices"})}
    if target == TARGET_BUDGET:
        return {"label": "Open limits & budgets", "href": _href({"area": "admin", "tab": "runtimeLimits"})}
    if target == TARGET_MODEL:
        return {"label": "Open the model", "href": _href({"area": "admin", "tab": "modelCatalog", "model": object_id})}
    raise ValueError(f"unknown problem fix target: {target}")


__all__ = [
    "TARGET_BUDGET",
    "TARGET_CONNECTION",
    "TARGET_DEVICE",
    "TARGET_INTAKE",
    "TARGET_KNOWLEDGE_SOURCE",
    "TARGET_MODEL",
    "TARGET_PROVIDER",
    "TARGET_RULE",
    "TARGET_SESSION",
    "TARGET_TASKS",
    "TARGET_WORK",
    "fix_link",
]
