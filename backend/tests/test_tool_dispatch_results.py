"""Contract tests for typed tool dispatch result metadata."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.circuit_breaker import CircuitBreakerDecision
from app.tools.context import ToolContext
from app.tools.registry import TOOL_REGISTRY, execute_tool, execute_tool_with_plugins
from app.tools.results import annotate_tool_result_payload, safe_tool_error_message
from tests.mcp_capability_support import RecordingMcpManager, create_mcp_workspace, enable_capability, mirror_tools


def _context(project_config: dict | None = None, *, db=None) -> ToolContext:
    return ToolContext(
        user_id="user-1",
        project_ids=["project-1"],
        roles=["member"],
        session_id="session-1",
        project_config=project_config or {},
        db=db,
        workspace_root="/tmp/workspace",
    )


def test_safe_tool_error_message_redacts_common_secret_shapes() -> None:
    message = safe_tool_error_message(
        "failed with token=abc1" + "23456789 and Bearer eyJhbGciOiVeryLongToken "
        "from https://user:super-secret@example.test/scm/repo.git"
    )

    assert ("abc1" + "23456789") not in message
    assert "eyJhbGciOiVeryLongToken" not in message
    assert "super-secret" not in message
    assert "token=[redacted]" in message
    assert "Bearer [redacted]" in message
    assert "https://[redacted]@example.test/scm/repo.git" in message


def test_annotate_tool_result_payload_adds_owner_identity_to_error() -> None:
    result = annotate_tool_result_payload(
        "search_jira_tickets",
        {"error": "Jira provider unavailable", "policy": "connector_runtime"},
        category="provider_error",
        reason="provider_call_failed",
    )

    execution = result["tool_execution"]
    assert execution["version"] == "tool_execution.v1"
    assert execution["status"] == "error"
    assert execution["category"] == "provider_error"
    assert execution["reason"] == "provider_call_failed"
    assert execution["policy"] == "connector_runtime"
    assert execution["owner"]["owner_type"] == "connector"
    assert execution["owner"]["connector"] == "jira"
    assert execution["owner"]["risk"] == "read"


async def test_unknown_tool_dispatch_error_is_typed_and_keeps_policy_payload() -> None:
    result = await execute_tool_with_plugins("mystery_enterprise_tool", {}, _context())

    execution = result["tool_execution"]
    assert result["policy"] == "tool_governance_metadata"
    assert result["policy_decision"]["reason"] == "unknown_tool_requires_metadata"
    assert execution["status"] == "error"
    assert execution["category"] == "denied_by_policy"
    assert execution["policy"] == "tool_governance_metadata"
    assert execution["owner"]["owner_type"] == "unknown"
    assert execution["owner"]["risk"] == "unknown"


async def test_inactive_connector_dispatch_error_is_typed() -> None:
    result = await execute_tool_with_plugins("search_jira_tickets", {"query": "OCX"}, _context())

    execution = result["tool_execution"]
    assert result["policy"] == "connector_activation"
    assert result["visibility_decision"]["reason"] == "connector_not_active_for_project"
    assert execution["status"] == "error"
    assert execution["category"] == "denied_by_policy"
    assert execution["policy"] == "connector_activation"
    assert execution["owner"]["owner_type"] == "connector"
    assert execution["owner"]["connector"] == "jira"


async def test_approval_required_dispatch_error_is_typed_without_database_context() -> None:
    result = await execute_tool_with_plugins(
        "create_jira_ticket",
        {"summary": "Needs review"},
        _context(
            {
                "connectors": {"jira": {"enabled": True}},
                "tool_policy": {"allowlist": ["create_jira_ticket"]},
                "approval_policy": {"require_for_risks": ["write"]},
            }
        ),
    )

    execution = result["tool_execution"]
    assert result["approval_status"] == "unverifiable"
    assert result["blocked_by"] == "tool_approval_gate"
    assert execution["status"] == "approval_required"
    assert execution["category"] == "approval_required"
    assert execution["policy"] == "tool_approval_gate"
    assert execution["owner"]["owner_type"] == "connector"
    assert execution["owner"]["connector"] == "jira"
    assert execution["owner"]["risk"] == "write"


async def test_registered_tool_exception_is_typed_and_redacted(monkeypatch) -> None:
    class ExplodingTool:
        name = "knowledge_search"

        async def execute(self, _params, _context):
            raise RuntimeError("provider failed with token=abc1" + "23456789")

    monkeypatch.setitem(TOOL_REGISTRY, "knowledge_search", ExplodingTool())

    result = await execute_tool("knowledge_search", {"query": "risk"}, _context())

    execution = result["tool_execution"]
    assert result["error"] == "Tool execution failed: provider failed with token=[redacted]"
    assert execution["category"] == "execution_error"
    assert execution["reason"] == "tool_exception"
    assert execution["owner"]["owner_type"] == "built_in"
    assert ("abc1" + "23456789") not in execution["message"]


async def test_plugin_tool_exception_is_typed_and_redacted(monkeypatch) -> None:
    from app.plugins.core import manager as plugin_manager_module

    class ExplodingPlugin:
        metadata = SimpleNamespace(id="governed")

        def get_tools(self):
            return [
                SimpleNamespace(
                    name="governed_plugin_tool",
                    description="Governed plugin tool",
                    parameters={"type": "object"},
                    risk="read",
                    scopes=("plugin:governed",),
                )
            ]

        async def execute(self, _params, _context):
            raise RuntimeError("provider failed with Authorization: Bearer abc1" + "23456789")

    monkeypatch.setattr(plugin_manager_module, "PLUGIN_INSTANCES", {"governed": ExplodingPlugin()})

    result = await execute_tool_with_plugins("governed_plugin_tool", {}, _context())

    execution = result["tool_execution"]
    assert result["error"] == "Plugin tool execution failed: provider failed with Authorization: Bearer [redacted]"
    assert result["reason"] == "plugin_tool_exception"
    assert execution["category"] == "execution_failed"
    assert execution["reason"] == "plugin_tool_exception"
    assert execution["owner"]["owner_type"] == "plugin"
    assert execution["owner"]["required_config"] == "plugin:governed"
    assert ("abc1" + "23456789") not in execution["message"]


async def test_direct_mcp_provider_failure_is_typed_and_redacted(db, monkeypatch) -> None:
    """The provider-failure taxonomy, reached through MCP capability governance.

    Direct ``mcp__*`` dispatch needs a verifiable workspace and an enabled capability binding, so this
    test runs against a real one whose ``resolve-library-id`` tool is mirrored and enabled; its subject is the
    error taxonomy, not the governance decision.
    """

    class FakeManager(RecordingMcpManager):
        async def call_tool(self, _server_name, _tool_name, _params):
            return {
                "error": "MCP tool execution failed: token=[redacted]",
                "source": "mcp",
                "error_category": "provider_failure",
                "reason": "mcp_tool_exception",
            }

    monkeypatch.setattr("app.plugins.mcp.client.mcp_client_manager", FakeManager())
    workspace = await create_mcp_workspace(db)
    # Direct dispatch connects only through the persisted Workspace registry.
    await mirror_tools(db, workspace, ["resolve-library-id"], server_name="context7")
    await enable_capability(db, workspace, "resolve-library-id", risk="read", server_name="context7")

    result = await execute_tool_with_plugins(
        "mcp__context7__resolve-library-id",
        {},
        _context(
            {"project_id": workspace.project.id, "mcp_policy": {"enabled_servers": ["context7"]}},
            db=db,
        ),
    )

    execution = result["tool_execution"]
    assert execution["category"] == "provider_failure"
    assert execution["reason"] == "mcp_tool_exception"
    assert execution["policy"] is None
    assert execution["owner"]["owner_type"] == "mcp"


async def test_circuit_breaker_provider_unavailable_error_is_typed(monkeypatch) -> None:
    async def fake_check_circuit_breaker(_db, connector_name):
        return CircuitBreakerDecision(
            allowed=False,
            connector_name=connector_name,
            state="open",
            reason="Circuit breaker is open for jira",
            next_retry_at="2026-07-02T02:30:00Z",
        )

    monkeypatch.setattr("app.services.circuit_breaker.check_circuit_breaker", fake_check_circuit_breaker)
    monkeypatch.setattr("app.services.circuit_breaker.infer_connector_name", lambda _tool_name: "jira")

    async def no_own_connection(*_args):
        return False

    monkeypatch.setattr(
        "app.services.connector_health.breaker_scope._workspace_has_own_connection", no_own_connection
    )

    async def no_workflow_run(*_args):
        return None

    # The governed dispatch first checks the session's workflow-run receiver; this session has no run.
    monkeypatch.setattr("app.services.workflow_runs.run_sessions.run_for_session", no_workflow_run)

    result = await execute_tool_with_plugins(
        "search_jira_tickets",
        {"jql": "project = RIVER"},
        _context({"connectors": {"jira": {"enabled": True}}}, db=object()),
    )

    execution = result["tool_execution"]
    assert result["circuit_breaker_state"] == "open"
    assert execution["category"] == "provider_unavailable"
    assert execution["policy"] == "circuit_breaker"
    assert execution["retryable"] is True
    assert execution["owner"]["connector"] == "jira"
