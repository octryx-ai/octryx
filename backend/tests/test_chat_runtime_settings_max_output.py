"""The global max output runtime setting is updated via the admin API, and invalid tool planner limits are refused."""

import pytest

from app.services.model_selection.platform_order import order_targets
from tests.conftest import ADMIN_PASSWORD

_RUNTIME_SETTINGS_UPDATE = {
    "max_output_tokens_default": 12000,
    "agent_default_model": "openai/gpt-4.1-mini",
    "execution_runtime_provider": "docker",
    "execution_runtime_docker_image": "python:3.12-slim",
    "execution_runtime_docker_network_mode": "bridge",
    "execution_runtime_allow_host_fallback": False,
    "execution_runtime_sandbox_mode": "hard",
    "execution_runtime_docker_memory_mb": 768,
    "execution_runtime_docker_pids_limit": 192,
    "session_workspace_storage_backend": "filesystem",
    "session_workspace_storage_bucket": "/tmp/session-workspace-objects",
    "session_workspace_storage_prefix": "octryx/test",
    "session_workspace_sync_excluded_dirs": "tmp-cache, reports",
    "session_workspace_sync_excluded_globs": "*.secret, *.tmp",
    "session_workspace_sync_max_file_size_bytes": 2048,
    "session_workspace_sync_max_file_count": 200,
    "office_template_library": [
        {
            "key": "deck-template",
            "name": "Deck Template",
            "doc_type": "pptx",
            "path": "/tmp/deck-template.potx",
            "description": "Default presentation template",
            "is_default": True,
        }
    ],
    "llm_security_analyzer_timeout_seconds": 12,
    "llm_security_analyzer_review_threshold": 35,
    "llm_security_analyzer_deny_threshold": 78,
    "stuck_loop_tool_repeat_threshold": 6,
    "stuck_loop_blocked_tool_threshold": 3,
    "stuck_loop_repeated_jira_threshold": 5,
    "stuck_loop_no_tool_duplicate_threshold": 2,
    "stuck_loop_summary_repeat_threshold": 2,
    "stuck_loop_no_tool_similarity_threshold": 0.81,
    "elastic_iteration_enabled": True,
    "elastic_iteration_max_bonus": 5,
    "elastic_iteration_unique_tool_threshold": 3,
    "security_analyzer_chain": ["secret_access", "exec_policy"],
    "default_completion_tokens": 5000,
    "extended_completion_tokens": 9000,
    "approx_chars_per_token": 5,
    "trace_max_string": 1200,
    "trace_max_list_items": 25,
    "trace_max_dict_items": 30,
    "saved_script_max_output_chars": 9000,
    "runtime_request_timeout_seconds": 45,
    "llm_cache_ttl_seconds": 600,
    "llm_cache_tools_ttl_seconds": 180,
    "llm_tool_planner_trace_call_enabled": True,
    "llm_tool_planner_max_tokens": 700,
    "llm_tool_planner_timeout_seconds": 20,
}


def _assert_runtime_settings_fields_present(get_resp) -> None:
    assert get_resp.status_code == 200
    assert "agent_default_model" in get_resp.json()
    assert "execution_runtime_provider" in get_resp.json()
    assert "execution_runtime_docker_image" in get_resp.json()
    assert "execution_runtime_docker_network_mode" in get_resp.json()
    assert "execution_runtime_allow_host_fallback" in get_resp.json()
    assert "execution_runtime_sandbox_mode" in get_resp.json()
    assert "execution_runtime_docker_memory_mb" in get_resp.json()
    assert "execution_runtime_docker_pids_limit" in get_resp.json()
    assert "officecli_binary_path" not in get_resp.json()  # Office runs in-process (no binary setting)
    assert "office_template_library" in get_resp.json()
    assert "llm_security_analyzer_timeout_seconds" in get_resp.json()
    assert "llm_security_analyzer_review_threshold" in get_resp.json()
    assert "llm_security_analyzer_deny_threshold" in get_resp.json()
    assert "stuck_loop_tool_repeat_threshold" in get_resp.json()
    assert "stuck_loop_blocked_tool_threshold" in get_resp.json()
    assert "stuck_loop_repeated_jira_threshold" in get_resp.json()
    assert "stuck_loop_no_tool_duplicate_threshold" in get_resp.json()
    assert "stuck_loop_summary_repeat_threshold" in get_resp.json()
    assert "stuck_loop_no_tool_similarity_threshold" in get_resp.json()
    assert "elastic_iteration_enabled" in get_resp.json()
    assert "elastic_iteration_max_bonus" in get_resp.json()
    assert "elastic_iteration_unique_tool_threshold" in get_resp.json()
    assert "security_analyzer_chain" in get_resp.json()
    assert "security_analyzer_options" in get_resp.json()
    assert "default_completion_tokens" in get_resp.json()
    assert "extended_completion_tokens" in get_resp.json()
    assert "approx_chars_per_token" in get_resp.json()
    assert "trace_max_string" in get_resp.json()
    assert "saved_script_max_output_chars" in get_resp.json()
    assert "runtime_request_timeout_seconds" in get_resp.json()
    assert "llm_cache_ttl_seconds" in get_resp.json()
    assert "llm_cache_tools_ttl_seconds" in get_resp.json()
    assert get_resp.json()["llm_tool_planner_trace_call_enabled"] is False
    assert get_resp.json()["llm_tool_planner_max_tokens"] == 900
    assert get_resp.json()["llm_tool_planner_timeout_seconds"] == 30
    assert "session_workspace_storage_backend" in get_resp.json()
    assert "session_workspace_storage_bucket" in get_resp.json()
    assert "session_workspace_storage_prefix" in get_resp.json()
    assert "session_workspace_sync_excluded_dirs" in get_resp.json()
    assert "session_workspace_sync_default_excluded_dirs" in get_resp.json()
    assert "session_workspace_sync_excluded_globs" in get_resp.json()
    assert "session_workspace_sync_default_excluded_globs" in get_resp.json()
    assert "session_workspace_sync_max_file_size_bytes" in get_resp.json()
    assert "session_workspace_sync_max_file_count" in get_resp.json()


def _assert_update_applied(update_resp, platform_default) -> None:
    assert update_resp.json()["max_output_tokens_default"] == 12000
    # The reported default model is the first of the platform order; the stored
    # value only seeds an install without any runtime target.
    assert update_resp.json()["agent_default_model"] == platform_default
    assert update_resp.json()["execution_runtime_provider"] == "docker"
    assert update_resp.json()["execution_runtime_docker_image"] == "python:3.12-slim"
    assert update_resp.json()["execution_runtime_docker_network_mode"] == "bridge"
    assert update_resp.json()["execution_runtime_allow_host_fallback"] is False
    assert update_resp.json()["execution_runtime_sandbox_mode"] == "hard"
    assert update_resp.json()["execution_runtime_docker_memory_mb"] == 768
    assert update_resp.json()["execution_runtime_docker_pids_limit"] == 192
    assert update_resp.json()["session_workspace_storage_backend"] == "filesystem"
    assert update_resp.json()["session_workspace_storage_bucket"] == "/tmp/session-workspace-objects"
    assert update_resp.json()["session_workspace_storage_prefix"] == "octryx/test"
    assert update_resp.json()["session_workspace_sync_excluded_dirs"] == "reports, tmp-cache"
    assert update_resp.json()["session_workspace_sync_excluded_globs"] == "*.secret, *.tmp"
    assert update_resp.json()["session_workspace_sync_max_file_size_bytes"] == 2048
    assert update_resp.json()["session_workspace_sync_max_file_count"] == 200
    assert update_resp.json()["office_template_library"][0]["key"] == "deck-template"
    assert update_resp.json()["llm_security_analyzer_timeout_seconds"] == 12
    assert update_resp.json()["llm_security_analyzer_review_threshold"] == 35
    assert update_resp.json()["llm_security_analyzer_deny_threshold"] == 78
    assert update_resp.json()["stuck_loop_tool_repeat_threshold"] == 6
    assert update_resp.json()["stuck_loop_blocked_tool_threshold"] == 3
    assert update_resp.json()["stuck_loop_repeated_jira_threshold"] == 5
    assert update_resp.json()["stuck_loop_no_tool_duplicate_threshold"] == 2
    assert update_resp.json()["stuck_loop_summary_repeat_threshold"] == 2
    assert update_resp.json()["stuck_loop_no_tool_similarity_threshold"] == pytest.approx(0.81)
    assert update_resp.json()["elastic_iteration_enabled"] is True
    assert update_resp.json()["elastic_iteration_max_bonus"] == 5
    assert update_resp.json()["elastic_iteration_unique_tool_threshold"] == 3
    assert update_resp.json()["security_analyzer_chain"] == ["secret_access", "exec_policy"]
    assert any(item["key"] == "command_guardrail" for item in update_resp.json()["security_analyzer_options"])
    assert update_resp.json()["default_completion_tokens"] == 5000
    assert update_resp.json()["extended_completion_tokens"] == 9000
    assert update_resp.json()["approx_chars_per_token"] == 5
    assert update_resp.json()["trace_max_string"] == 1200
    assert update_resp.json()["trace_max_list_items"] == 25
    assert update_resp.json()["trace_max_dict_items"] == 30
    assert update_resp.json()["saved_script_max_output_chars"] == 9000
    assert update_resp.json()["runtime_request_timeout_seconds"] == 45
    assert update_resp.json()["llm_cache_ttl_seconds"] == 600
    assert update_resp.json()["llm_cache_tools_ttl_seconds"] == 180
    assert update_resp.json()["llm_tool_planner_trace_call_enabled"] is True
    assert update_resp.json()["llm_tool_planner_max_tokens"] == 700
    assert update_resp.json()["llm_tool_planner_timeout_seconds"] == 20


def _assert_settings_persisted(get_resp, platform_default) -> None:
    assert get_resp.json()["max_output_tokens_default"] == 12000
    assert get_resp.json()["agent_default_model"] == platform_default
    assert get_resp.json()["execution_runtime_provider"] == "docker"
    assert get_resp.json()["execution_runtime_docker_image"] == "python:3.12-slim"
    assert get_resp.json()["execution_runtime_docker_network_mode"] == "bridge"
    assert get_resp.json()["execution_runtime_allow_host_fallback"] is False
    assert get_resp.json()["execution_runtime_sandbox_mode"] == "hard"
    assert get_resp.json()["session_workspace_storage_backend"] == "filesystem"
    assert get_resp.json()["session_workspace_storage_bucket"] == "/tmp/session-workspace-objects"
    assert get_resp.json()["session_workspace_storage_prefix"] == "octryx/test"
    assert get_resp.json()["session_workspace_sync_excluded_dirs"] == "reports, tmp-cache"
    assert get_resp.json()["session_workspace_sync_excluded_globs"] == "*.secret, *.tmp"
    assert get_resp.json()["session_workspace_sync_max_file_size_bytes"] == 2048
    assert get_resp.json()["session_workspace_sync_max_file_count"] == 200
    assert get_resp.json()["execution_runtime_docker_memory_mb"] == 768
    assert get_resp.json()["execution_runtime_docker_pids_limit"] == 192
    assert get_resp.json()["office_template_library"][0]["key"] == "deck-template"
    assert get_resp.json()["llm_security_analyzer_timeout_seconds"] == 12
    assert get_resp.json()["llm_security_analyzer_review_threshold"] == 35
    assert get_resp.json()["llm_security_analyzer_deny_threshold"] == 78
    assert get_resp.json()["stuck_loop_tool_repeat_threshold"] == 6
    assert get_resp.json()["stuck_loop_blocked_tool_threshold"] == 3
    assert get_resp.json()["stuck_loop_repeated_jira_threshold"] == 5
    assert get_resp.json()["stuck_loop_no_tool_duplicate_threshold"] == 2
    assert get_resp.json()["stuck_loop_summary_repeat_threshold"] == 2
    assert get_resp.json()["stuck_loop_no_tool_similarity_threshold"] == pytest.approx(0.81)
    assert get_resp.json()["elastic_iteration_enabled"] is True
    assert get_resp.json()["elastic_iteration_max_bonus"] == 5
    assert get_resp.json()["elastic_iteration_unique_tool_threshold"] == 3
    assert get_resp.json()["security_analyzer_chain"] == ["secret_access", "exec_policy"]
    assert any(item["key"] == "command_guardrail" for item in get_resp.json()["security_analyzer_options"])
    assert get_resp.json()["default_completion_tokens"] == 5000
    assert get_resp.json()["extended_completion_tokens"] == 9000
    assert get_resp.json()["approx_chars_per_token"] == 5
    assert get_resp.json()["trace_max_string"] == 1200
    assert get_resp.json()["trace_max_list_items"] == 25
    assert get_resp.json()["trace_max_dict_items"] == 30
    assert get_resp.json()["saved_script_max_output_chars"] == 9000
    assert get_resp.json()["runtime_request_timeout_seconds"] == 45
    assert get_resp.json()["llm_cache_ttl_seconds"] == 600
    assert get_resp.json()["llm_cache_tools_ttl_seconds"] == 180
    assert get_resp.json()["llm_tool_planner_trace_call_enabled"] is True
    assert get_resp.json()["llm_tool_planner_max_tokens"] == 700
    assert get_resp.json()["llm_tool_planner_timeout_seconds"] == 20


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_runtime_settings_global_max_output_can_be_updated_via_admin_api(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    get_resp = await client.get("/admin/chat/api/panel/runtime-settings")
    _assert_runtime_settings_fields_present(get_resp)

    update_resp = await client.put(
        "/admin/chat/api/panel/runtime-settings",
        json=_RUNTIME_SETTINGS_UPDATE,
    )
    assert update_resp.status_code == 200
    platform_default = (await order_targets(db))[0].model_id
    _assert_update_applied(update_resp, platform_default)

    get_resp = await client.get("/admin/chat/api/panel/runtime-settings")
    assert get_resp.status_code == 200
    _assert_settings_persisted(get_resp, platform_default)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_runtime_settings_reject_invalid_tool_planner_limits(client):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    low_tokens_resp = await client.put(
        "/admin/chat/api/panel/runtime-settings",
        json={"llm_tool_planner_max_tokens": 1},
    )
    assert low_tokens_resp.status_code == 422

    high_timeout_resp = await client.put(
        "/admin/chat/api/panel/runtime-settings",
        json={"llm_tool_planner_timeout_seconds": 999999},
    )
    assert high_timeout_resp.status_code == 422
