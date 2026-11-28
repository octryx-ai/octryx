"""Admin-only mutations served outside an ``admin``/``panel`` path, refused by the gate for any non-admin."""

from __future__ import annotations

_CHAT_ROOT_MOUNTS = {
    # Root twins of the ``/admin`` chat routers (``web/__init__.py`` mounts them at both).
    ("POST", "/budget-policies"),
    ("PUT", "/chat/api/v1/tts/config"),
    ("POST", "/chat/api/v1/tts/providers"),
    ("DELETE", "/chat/api/v1/tts/providers/{provider_id}"),
    ("POST", "/chat/api/v1/tts/providers/{provider_id}/move"),
    ("POST", "/chat/api/v1/tts/synthesize"),
    ("DELETE", "/chat/api/sessions/{session_id}"),
}

_WORKSPACES_AND_PROVIDERS = {
    ("POST", "/api/v1/projects"),
    ("PATCH", "/api/v1/projects/{project_id}"),
    ("DELETE", "/api/v1/projects/{project_id}"),
    ("POST", "/api/v1/projects/{project_id}/archive"),
    ("POST", "/api/v1/projects/{project_id}/restore"),
    ("POST", "/api/v1/projects/{project_id}/make-default"),
    ("PUT", "/api/v1/projects/{project_id}/config"),
    ("POST", "/api/v1/tasks/scheduler/reload"),
}

_OBSERVABILITY = {
    ("POST", "/api/v1/reports/export"),
}

_PROMPTS_AND_WORKFLOW_GOVERNANCE = {
    # A phase of a workflow that runs in phases, edited in the Steps canvas.
    # The designer creates the workflow and saves its whole definition as a draft.
    ("POST", "/api/v1/phased-workflows"),
    ("POST", "/api/v1/phased-workflows/{flow_id}/definition"),
    ("POST", "/api/v1/phased-workflows/{flow_id}/layout"),
    ("POST", "/api/v1/phased-workflows/{flow_id}/phases/{node_id}/graph"),
    ("POST", "/api/v1/phased-workflows/{flow_id}/phases/{node_id}/graph/preview"),
}

_FLOWS = {
    ("POST", "/api/v1/flows"),
    ("POST", "/api/v1/flows/validate"),
    ("POST", "/api/v1/flows/generate-from-session/{session_id}"),
    ("POST", "/api/v1/flows/{flow_id}/drafts"),
    ("POST", "/api/v1/flows/{flow_id}/archive"),
    # An optional shipped workflow switched on or off by a platform admin (no draft or version change).
    ("POST", "/api/v1/flows/{flow_id}/active"),
    ("POST", "/api/v1/flows/versions/{version_id}/publish"),
    # Four-eyes publish: the author asks a second admin to publish.
    ("POST", "/api/v1/flows/versions/{version_id}/request-review"),
}

ADMIN_ONLY_ROUTES_OUTSIDE_ADMIN_PATH: frozenset[tuple[str, str]] = frozenset(
    _CHAT_ROOT_MOUNTS
    | _WORKSPACES_AND_PROVIDERS
    | _OBSERVABILITY
    | _PROMPTS_AND_WORKFLOW_GOVERNANCE
    | _FLOWS
)

__all__ = ["ADMIN_ONLY_ROUTES_OUTSIDE_ADMIN_PATH"]
