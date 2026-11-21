"""The intentionally user-level routes served under an admin path.

``admin_surface_gate.py`` refuses every state-changing route with an ``admin`` or ``panel`` path
segment unless the caller is admin-capable. The routes below are the exceptions. Every one is
the ``/admin``-mounted twin of a chat route that is also served at the root (``web/__init__.py``
includes the chat routers both at the root and under ``/admin``), or the login itself. Each still
runs its own authentication and its own ownership or approver check. An entry is an exact
``(METHOD, path template)``, so a new route is never exempt by accident; adding one is a reviewed
decision with its reason, and ``tests/test_admin_surface_gate.py`` proves the list is exact.
"""

from __future__ import annotations

_LOGIN = {
    # Before any principal exists: the admin login form posts here.
    ("POST", "/admin/login"),
}

_CHAT_TURNS = {
    # A user sends, uploads for and resolves artifact actions in their own chat (owner-scoped).
    ("POST", "/admin/chat/api/send"),
    ("POST", "/admin/chat/api/upload"),
    ("POST", "/admin/chat/api/artifact-actions/resolve"),
    ("POST", "/admin/chat/api/sessions/{session_id}/workflow-proposal"),
    ("POST", "/admin/chat/api/sessions/{session_id}/generate-task"),
}

_CHAT_SESSIONS = {
    # The session owner manages their own session and its workspace files. Deleting a session and
    # text to speech are not here: their handlers require the global admin role
    # (``admin_surface_root_routes.py`` lists the root twins).
    ("POST", "/admin/chat/api/sessions/{session_id}/continue"),
    ("POST", "/admin/chat/api/sessions/{session_id}/stop"),
    ("POST", "/admin/chat/api/sessions/{session_id}/archive"),
    ("POST", "/admin/chat/api/sessions/{session_id}/restore"),
    ("POST", "/admin/chat/api/sessions/{session_id}/pin"),
    ("POST", "/admin/chat/api/sessions/{session_id}/unpin"),
    ("POST", "/admin/chat/api/sessions/{session_id}/rename"),
    ("POST", "/admin/chat/api/sessions/{session_id}/workspace/folders"),
    ("POST", "/admin/chat/api/sessions/{session_id}/workspace/rename"),
    ("POST", "/admin/chat/api/sessions/{session_id}/workspace/move"),
    ("POST", "/admin/chat/api/sessions/{session_id}/workspace/delete"),
    ("POST", "/admin/chat/api/sessions/{session_id}/workspace/clean"),
    ("POST", "/admin/chat/api/sessions/{session_id}/messages/{message_id}/feedback"),
    ("POST", "/admin/chat/api/sessions/{session_id}/messages/{message_id}/rerun"),
    ("POST", "/admin/chat/api/sessions/{session_id}/tool-calls/{tool_call_id}/rerun"),
    ("POST", "/admin/chat/api/sessions/{session_id}/approvals/{approval_id}/rerun"),
    ("POST", "/admin/chat/api/sessions/{session_id}/change-previews/{change_preview_id}/rerun"),
}

_CHAT_APPROVALS = {
    # The designated approver decides a pending approval (``require_approval_decision_access``).
    ("POST", "/admin/chat/api/approvals/{approval_id}/approve"),
    ("POST", "/admin/chat/api/approvals/{approval_id}/reject"),
}

USER_LEVEL_ADMIN_SURFACE_ROUTES: frozenset[tuple[str, str]] = frozenset(
    _LOGIN | _CHAT_TURNS | _CHAT_SESSIONS | _CHAT_APPROVALS
)

__all__ = ["USER_LEVEL_ADMIN_SURFACE_ROUTES"]
