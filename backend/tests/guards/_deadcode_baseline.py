from __future__ import annotations

from tests.guards._support import Accepted, Allowed

_WP = "WP-C4"
_NO_CALLER = "no caller anywhere in the repository: delete it"
_TEST_ONLY = "no product caller; only its tests call it: delete it with its tests"
_TEST_SEAM = "test seam: resets or drains process-wide state between tests"
_MODULE_PROTOCOL = "module protocol: Python calls a package's __getattr__ and __dir__ for its lazy exports"
_LIBRARY_CALLBACK = ("overrides a method the library calls (httpx.Auth, HTMLParser, httpcore network backend, "
                     "Starlette StaticFiles, Graphiti driver and embedder, MCP token verifier)")
_SERVICE_TABLE = "called by name through the tool runtime's service tables (_runtime_code_service_resolvers)"
_RETRIEVAL_MODE = "called by name: the retrieval facade looks the store method up per retrieval mode"
_DOCUMENTATION_INTERFACE = "called by name through the documentation graph's INTERFACES table (s1_graph)"
_MIGRATION_ENTRY = "called from backend/alembic/env.py, outside the scanned app package"
_RETENTION_HOLD = ("the write side of the retention hold that publication and the reconcile honour: only a deleting "
                   "retention mode takes one, and none exists")
_LIBRARY_SIGNATURE = ("override of Graphiti's GraphDriver.build_indices_and_constraints: the parameter belongs to the "
                      "signature the library calls; the refusing stand-in has no use for it")


def _findings(path: str, findings: tuple[str, ...]) -> list[str]:
    return [f"{path}: unused {kind} '{name}'" for kind, _, name in (finding.partition(" ") for finding in findings)]


def _allowed(reason: str, path: str, *findings: str, wp: str = _WP) -> list[Allowed]:
    return [Allowed(key, reason, wp) for key in _findings(path, findings)]


def _accepted(reason: str, path: str, *findings: str) -> list[Accepted]:
    return [Accepted(key, reason) for key in _findings(path, findings)]


DEAD_CODE_BASELINE: tuple[Allowed | Accepted, ...] = (
    *_allowed(_RETENTION_HOLD, "app/services/knowledge/retention/holds.py", "function release_hold", wp="WP-KR1"),
    *_allowed(_NO_CALLER, "app/services/secure_work/access.py", "function get_visible_change_plan"),
    *_allowed(_TEST_ONLY, "app/db/sqlite.py", "function sqlite_backup_candidates", "function sqlite_sidecar_paths"),
    *_allowed(_TEST_ONLY, "app/plugins/__init__.py", "method get_status"),
    *_allowed(_TEST_ONLY, "app/plugins/mcp/client.py", "method get_auth_status"),
    *_allowed(_TEST_ONLY, "app/scheduler/coordination/coordinator.py", "method registered_fingerprints"),
    *_allowed(_TEST_ONLY, "app/scheduler/dispatch/loop.py", "method _wait_for_dispatched_runs"),
    *_allowed(_TEST_ONLY, "app/scheduler/execution/step_executor.py", "method _render_template_str"),
    *_allowed(_TEST_ONLY, "app/services/admin/project/admin_project_access_service.py", "function replace_project_user_access"),
    *_allowed(_TEST_ONLY, "app/services/agent_definition_authoring/scope.py", "method record_for"),
    *_allowed(_TEST_ONLY, "app/services/call_agent/service.py", "method _llm_with_tools"),
    *_allowed(_TEST_ONLY, "app/services/clarification_service.py", "function get_clarification_by_id"),
    *_allowed(_TEST_ONLY, "app/services/compliance_audit/service.py",
        "function create_evidence_package", "function export_evidence_package", "function list_evidence_packages",
        "function seal_evidence_package"),
    *_allowed(_TEST_ONLY, "app/services/content_detection/examination.py", "method clean_entry"),
    *_allowed(_TEST_ONLY, "app/services/double_text_guard_service.py",
        "function mark_session_complete", "function mark_session_failed", "function mark_session_running"),
    *_allowed(_RETENTION_HOLD, "app/services/knowledge/retention/holds.py", "function acquire_hold", wp="WP-KR1"),
    *_allowed(_TEST_ONLY, "app/services/knowledge/retrieval/contracts.py", "method for_mode"),
    *_allowed(_TEST_ONLY, "app/services/observability/cost_states.py", "function cost_state"),
    *_allowed(_TEST_ONLY, "app/services/outbound_url_policy.py", "function validate_outbound_url"),
    *_allowed(_TEST_ONLY, "app/services/resume_checkpoint_service.py",
        "function attempt_resume", "function get_active_checkpoint_for_session",
        "function get_session_recovery_policy", "function mark_resume_failed", "function mark_resume_success"),
    *_allowed(_TEST_ONLY, "app/services/security_scope_contract.py",
        "function core_role_scopes", "function scope_contract_summary"),
    *_allowed(_TEST_ONLY, "app/services/skill_usage_trace_service.py", "function summarize_skill_usage"),
    *_allowed(_TEST_ONLY, "app/services/workflow_runs/documentation/audience_principals.py",
        "function audience_configuration_refusal"),
    *_allowed(_TEST_ONLY, "app/services/workflow_runs/octryx/agent_view.py", "function agent_view"),
    *_allowed(_TEST_ONLY, "app/services/workflow_runs/octryx/declared_commands.py", "function run_green"),
    *_allowed(_TEST_ONLY, "app/tools/base.py", "function build_tool"),
    *_allowed(_TEST_ONLY, "app/tools/bitbucket_impl/_bitbucket_internal_core.py",
        "function _bitbucket_credentials_async", "function _redact_bitbucket_git_output"),
    *_allowed(_TEST_ONLY, "app/tools/connectors/common.py", "function connection_http_text"),
    *_allowed(_TEST_ONLY, "app/tools/definitions/__init__.py",
        "function get_core_tool_names", "function get_discoverable_tool_names"),
    *_allowed(_TEST_ONLY, "app/tools/office_impl/_office_core_helpers.py",
        "function _resolve_builtin_generic_presentation_template"),
    *_allowed(_TEST_ONLY, "app/tools/office_impl/_office_presentation_script.py", "method _build_text_ops_code"),
    *_allowed(_TEST_ONLY, "app/tools/registry.py",
        "function get_tool_registry_entry", "function get_tool_registry_owner_summary",
        "function list_tool_registry_entries"),
    *_allowed(_TEST_ONLY, "app/tools/runtime_impl/_runtime_cli_helpers.py",
        "function _apply_search_query_filters", "function _normalize_domain_token", "function _search_result_allowed"),
    *_accepted(_TEST_SEAM, "app/middleware/security/rate_limit.py", "function clear_rate_limit_buckets"),
    *_accepted(_TEST_SEAM, "app/runtime_lifecycle.py", "function replace_platform_runtime_for_tests"),
    *_accepted(_TEST_SEAM, "app/services/chat_turn_background.py",
        "function cancel_chat_turn_background_tasks", "function drain_chat_turn_background_tasks"),
    *_accepted(_TEST_SEAM, "app/services/db_concurrency_observability.py", "function reset_db_concurrency_events"),
    *_accepted(_TEST_SEAM, "app/services/mcp_knowledge_observability.py", "function clear_mcp_knowledge_observability_state"),
    *_accepted(_TEST_SEAM, "app/services/observability/health_checks.py", "function forget_platform_health_checks"),
    *_accepted(_TEST_SEAM, "app/services/observability/request_metrics.py", "function reset_recent_requests"),
    *_accepted(_TEST_SEAM, "app/services/session/stream.py", "method clear_run_tracking"),
    *_accepted(_MODULE_PROTOCOL, "app/services/code_intelligence/__init__.py", "function __dir__", "function __getattr__"),
    *_accepted(_MODULE_PROTOCOL, "app/services/observability/__init__.py", "function __getattr__"),
    *_accepted(_MODULE_PROTOCOL, "app/services/office/__init__.py", "function __dir__", "function __getattr__"),
    *_accepted(_MODULE_PROTOCOL, "app/services/session/__init__.py", "function __dir__", "function __getattr__"),
    *_accepted(_MODULE_PROTOCOL, "app/services/stt/__init__.py", "function __getattr__"),
    *_accepted(_MODULE_PROTOCOL, "app/services/system_config/__init__.py", "function __getattr__"),
    *_accepted(_MODULE_PROTOCOL, "app/services/worker/__init__.py", "function __getattr__"),
    *_accepted(_MODULE_PROTOCOL, "app/tools/__init__.py", "function __getattr__"),
    *_accepted(_MODULE_PROTOCOL, "app/web/__init__.py", "function __getattr__"),
    *_accepted(_LIBRARY_CALLBACK, "app/services/connector_auth/atlassian.py", "method auth_flow"),
    *_accepted(_LIBRARY_CALLBACK, "app/services/knowledge/display/html_view.py",
        "method handle_data", "method handle_startendtag"),
    *_accepted(_LIBRARY_CALLBACK, "app/services/knowledge/eval/change_typing.py", "method build_indices_and_constraints"),
    *_accepted(_LIBRARY_CALLBACK, "app/services/knowledge/temporal/graphiti_adapters.py", "method create_batch"),
    *_accepted(_LIBRARY_CALLBACK, "app/services/mcp_knowledge_protocol.py", "method verify_token"),
    *_accepted(_LIBRARY_CALLBACK, "app/services/connector_auth/oidc_token_cache.py", "method async_auth_flow", "method auth_flow"),
    *_accepted(_LIBRARY_CALLBACK, "app/services/outbound_egress/pinned_transport.py", "method connect_unix_socket"),
    *_accepted(_LIBRARY_CALLBACK, "app/services/connector_auth/servicenow_password_grant.py", "method async_auth_flow", "method auth_flow"),
    *_accepted(_LIBRARY_CALLBACK, "app/services/workflow_runs/documentation/audience_query_set.py", "method handle_data"),
    *_accepted(_LIBRARY_CALLBACK, "app/services/workflow_runs/documentation/confluence_v2_storage.py",
        "method handle_data", "method handle_decl", "method handle_startendtag"),
    *_accepted(_LIBRARY_CALLBACK, "app/web/static_files.py", "method file_response"),
    *_accepted(_SERVICE_TABLE, "app/services/code_intelligence/graph_analytics.py",
        "function get_code_graph_god_nodes", "function get_code_graph_stats"),
    *_accepted(_SERVICE_TABLE, "app/services/code_intelligence/graph_context.py", "function get_code_graph_context"),
    *_accepted(_SERVICE_TABLE, "app/services/code_intelligence/graph_path_queries.py",
        "function get_code_graph_files", "function get_code_graph_trace"),
    *_accepted(_SERVICE_TABLE, "app/services/code_intelligence/graph_queries.py",
        "function get_code_graph_callees", "function get_code_graph_node", "function get_code_graph_status"),
    *_accepted(_SERVICE_TABLE, "app/services/code_intelligence/outline_queries.py", "function get_file_outline"),
    *_accepted(_SERVICE_TABLE, "app/services/code_intelligence/queries.py",
        "function get_graph_summary", "function search_repository_code"),
    *_accepted(_SERVICE_TABLE, "app/services/git_intelligence_service.py",
        "function git_conflict_predictor", "function git_coupling_map", "function git_file_intelligence",
        "function git_function_blame", "function git_hotspot_analysis", "function git_knowledge_extract",
        "function git_pr_context"),
    *_accepted(_RETRIEVAL_MODE, "app/services/knowledge/retrieval/index_query_store.py",
        "method search_graph", "method search_lexical", "method search_vector"),
    *_accepted(_RETRIEVAL_MODE, "app/services/knowledge/retrieval/query_store.py",
        "method search_graph", "method search_lexical", "method search_vector"),
    *_accepted(_DOCUMENTATION_INTERFACE, "app/services/workflow_runs/documentation/knowledge.py",
        "function sync_published_version"),
    *_accepted(_DOCUMENTATION_INTERFACE, "app/services/workflow_runs/documentation/publication_v2.py",
        "function publish_documentation_v2"),
    *_accepted(_MIGRATION_ENTRY, "app/db/migration_metadata.py", "function load_migration_metadata"),
    *_accepted(_LIBRARY_SIGNATURE, "app/services/knowledge/eval/change_typing.py", "variable delete_existing"),
)
