"""By-ID routes whose owner cannot read the seeded row in a test, so the walker has no positive control for them; list
routes whose answer may change between two calls anyway (still checked for every seeded row's id)."""

from __future__ import annotations

_FILES = "reads files or process state, not a Workspace row"
_PLATFORM = "reads a platform row without a Workspace under this parameter"
_GATEWAY = "authenticates with an agent-gateway token, not a session"
_INTERACTIVE = "needs an interactive (cookie) login"
_STORE = "needs the Postgres knowledge store or an attachment store, absent in the test database"
_STATE = "needs route state the generic seed does not build"
_SAME_REQUEST = "its other path parameter is no seeded row, so the request names nothing that exists"

NO_POSITIVE_CONTROL: dict[str, str] = {
    "/admin/chat/api/panel/corp-identities/{profile_id} profile_id": _FILES,
    "/admin/chat/api/panel/corp-identities/{profile_id}/corporate-identity profile_id": _FILES,
    "/admin/chat/api/panel/engineering-knowledge/build-runs/{build_run_id} build_run_id": _PLATFORM,
    "/admin/chat/api/panel/knowledge/entity-graph/node/{node_id} node_id":
        "the admin panel leaves out every private Workspace's nodes, its owner's too",
    "/admin/chat/api/panel/rest-apis/{definition_id} definition_id": _PLATFORM,
    "/admin/chat/api/panel/rest-apis/{definition_id}/connections definition_id": _PLATFORM,
    "/api/v1/admin/policy-engine/policy-sets/{version}/policies/{policy_id:path} policy_id": _SAME_REQUEST,
    "/api/v1/agent-board/handoff-attachments/{attachment_id} attachment_id": _STORE,
    "/api/v1/agent-gateway/git/{run_id}/info/refs run_id": "authenticates with a run-bound git token, not a session",
    "/api/v1/agent-gateway/handoff/attachments/{attachment_id} attachment_id": _GATEWAY,
    "/api/v1/agent-gateway/handoff/takeovers/{takeover_id} takeover_id": _GATEWAY,
    "/api/v1/canvas/sessions/{session_id} session_id": "a canvas lives in process memory, not in the database",
    "/api/v1/data/exports/{job_id}/download job_id": "needs an export file on disk",
    "/api/v1/device-jobs/{job_id}/files/{file_id} job_id": _INTERACTIVE,
    "/api/v1/device-jobs/{job_id}/files/{file_id} file_id": _INTERACTIVE,
    "/api/v1/device-jobs/{job_id}/files/{file_id}/content job_id": _INTERACTIVE,
    "/api/v1/device-jobs/{job_id}/files/{file_id}/content file_id": _INTERACTIVE,
    "/api/v1/devices/jobs/{job_id}/session-state job_id":
        "authenticates with the device credential of the job's active turn, not a session",
    "/api/v1/flows/{flow_id}/versions/{version_id}/composition flow_id": _SAME_REQUEST,
    "/api/v1/phased-workflows/{flow_id} flow_id": "needs a phased workflow definition",
    "/api/v1/phased-workflows/{flow_id}/phases/{node_id}/graph flow_id": "needs a phased workflow definition",
    "/api/v1/phased-workflows/{flow_id}/phases/{node_id}/graph node_id": "needs a phased workflow definition",
    "/api/v1/teams/calls/{call_id}/audio/temp/{file_id} file_id": _FILES,
    "/api/v1/workflow-handoffs/{handoff_id} handoff_id": "only the handoff's receiver previews it",
    "/api/v1/workflow-runs/{run_id}/screens/{name} run_id": _SAME_REQUEST,
    "/api/v1/workflow-runs/{run_id}/spec-studio run_id": _STATE,
    "/api/v1/workflow-runs/{run_id}/spec-studio/baseline run_id": _STATE,
    "/api/v1/workspaces/{workspace_id}/knowledge/connections/{connection_id}/repositories connection_id":
        "needs a reachable repository host on the connection",
    "/api/v1/workspaces/{workspace_id}/knowledge/connections/{connection_id}/repositories/{project_key}/{slug}"
    "/default-branch connection_id": "needs a reachable repository host on the connection",
    "/api/v1/workspaces/{workspace_id}/knowledge/graph/explorer/nodes/{node_id} node_id": _STORE,
    "/api/v1/workspaces/{workspace_id}/knowledge/sources/{source_id}/revisions/{revision_id}/original source_id": _STORE,
    "/api/v1/workspaces/{workspace_id}/knowledge/sources/{source_id}/revisions/{revision_id}/original revision_id":
        _STORE,
    "/api/v1/workspaces/{workspace_id}/knowledge/sources/{source_id}/revisions/{revision_id}/view source_id": _STORE,
    "/api/v1/workspaces/{workspace_id}/knowledge/sources/{source_id}/revisions/{revision_id}/view revision_id": _STORE,
    "/plugin-ui/{install_id}/{token}/{path:path} install_id":
        "its token is part of the path (covered by test_machine_principals)",
}

VOLATILE_LISTS: dict[str, str] = {
    "/api/v1/health": "no rows or ids, only platform totals; its timings and worker states change between calls",
}
