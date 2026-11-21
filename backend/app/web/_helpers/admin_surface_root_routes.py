"""Admin-only mutations served outside an ``admin``/``panel`` path.

The admin-surface gate (``admin_surface_gate.py``) recognises the admin surface by an ``admin`` or
``panel`` path segment. The routes below are admin-only too, but their path has neither segment:
chat routes mounted at the root (``/budget-policies``, ``/chat/api/v1/tts/...``) and ``/api/v1``
routes whose handler checks the global admin role inside its body (after request-body
validation). Each is listed as an exact ``(METHOD, path template)``, grouped by domain, and the
gate refuses a caller who is not a global admin before the route runs, whatever the body.

The handlers keep their own check. ``tests/test_admin_surface_gate.py`` proves the list is exact:
every entry is served, and every served state-changing route outside the admin path whose handler
requires the global admin role unconditionally is listed here or has the admin dependency.
"""

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
    ("POST", "/api/v1/providers/bedrock/pricing/sync"),
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
    ("POST", "/api/v1/flows/versions/{version_id}/unpublish"),
    # Four-eyes publish: the author asks a second admin to publish.
    ("POST", "/api/v1/flows/versions/{version_id}/request-review"),
    ("POST", "/api/v1/flows/versions/{version_id}/run"),
    ("POST", "/api/v1/flows/versions/{version_id}/partial-run"),
    ("POST", "/api/v1/flows/capabilities/{tool_name}/run"),
    ("POST", "/api/v1/flows/runs/recover-stale"),
    ("POST", "/api/v1/flows/runs/{run_id}/evaluate"),
    ("POST", "/api/v1/flows/runs/{run_id}/resume"),
    ("POST", "/api/v1/flows/runs/{run_id}/resume-interrupted"),
    ("POST", "/api/v1/flows/runs/{run_id}/cancel"),
    ("POST", "/api/v1/flows/{flow_id}/test-cases"),
    ("PUT", "/api/v1/flows/{flow_id}/test-cases/{test_case_id}"),
    ("DELETE", "/api/v1/flows/{flow_id}/test-cases/{test_case_id}"),
    ("POST", "/api/v1/flows/{flow_id}/test-cases/{test_case_id}/run"),
    ("POST", "/api/v1/flows/{flow_id}/test-cases/batch-run"),
}

ADMIN_ONLY_ROUTES_OUTSIDE_ADMIN_PATH: frozenset[tuple[str, str]] = frozenset(
    _CHAT_ROOT_MOUNTS
    | _WORKSPACES_AND_PROVIDERS
    | _OBSERVABILITY
    | _PROMPTS_AND_WORKFLOW_GOVERNANCE
    | _FLOWS
)

__all__ = ["ADMIN_ONLY_ROUTES_OUTSIDE_ADMIN_PATH"]
