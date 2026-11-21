from app.services.elastic_iteration import (
    DEFAULT_ELASTIC_ITERATION_ENABLED,
    DEFAULT_ELASTIC_ITERATION_MAX_BONUS,
    DEFAULT_ELASTIC_ITERATION_UNIQUE_TOOL_THRESHOLD,
    compute_elastic_step_iteration_limit,
    get_elastic_iteration_settings,
)
from app.services.elastic_iteration import (
    DEFAULT_ELASTIC_ITERATION_ENABLED as PACKAGE_DEFAULT_ENABLED,
)
from app.services.elastic_iteration import (
    DEFAULT_ELASTIC_ITERATION_MAX_BONUS as PACKAGE_DEFAULT_MAX_BONUS,
)
from app.services.elastic_iteration import (
    DEFAULT_ELASTIC_ITERATION_UNIQUE_TOOL_THRESHOLD as PACKAGE_DEFAULT_UNIQUE_TOOL_THRESHOLD,
)
from app.services.elastic_iteration import (
    compute_elastic_step_iteration_limit as package_compute_elastic_step_iteration_limit,
)
from app.services.elastic_iteration import (
    get_elastic_iteration_settings as package_get_elastic_iteration_settings,
)


def test_elastic_iteration_root_shim_matches_package_exports():
    assert compute_elastic_step_iteration_limit is package_compute_elastic_step_iteration_limit
    assert get_elastic_iteration_settings is package_get_elastic_iteration_settings
    assert DEFAULT_ELASTIC_ITERATION_ENABLED is PACKAGE_DEFAULT_ENABLED
    assert DEFAULT_ELASTIC_ITERATION_MAX_BONUS is PACKAGE_DEFAULT_MAX_BONUS
    assert DEFAULT_ELASTIC_ITERATION_UNIQUE_TOOL_THRESHOLD is PACKAGE_DEFAULT_UNIQUE_TOOL_THRESHOLD


def test_elastic_iteration_adds_bonus_for_multi_tool_progress():
    result = compute_elastic_step_iteration_limit(
        step={"name": "Investigate", "stepType": "analysis"},
        base_limit=8,
        step_tool_history=[
            {"tool_name": "search_jira_tickets", "result": {}},
            {"tool_name": "list_recent_bitbucket_commits", "result": {}},
            {"tool_name": "list_confluence_page_updates", "result": {}},
        ],
        wrapup_forced=False,
        runtime_settings={
            "elastic_iteration_enabled": True,
            "elastic_iteration_max_bonus": 6,
            "elastic_iteration_unique_tool_threshold": 2,
        },
    )

    assert result["bonus"] > 0
    assert result["effective_limit"] > 8
    assert result["reason"] == "multi_tool_progress"


def test_elastic_iteration_stays_flat_when_blocked_attempts_exist():
    result = compute_elastic_step_iteration_limit(
        step={"name": "Investigate", "stepType": "analysis"},
        base_limit=8,
        step_tool_history=[
            {
                "tool_name": "delete_workspace_file",
                "result": {"error": "Tool 'delete_workspace_file' is not allowed in the current step"},
            }
        ],
        wrapup_forced=False,
        runtime_settings={"elastic_iteration_enabled": True},
    )

    assert result["bonus"] == 0
    assert result["effective_limit"] == 8
    assert result["reason"] == "blocked_attempts"


def test_elastic_iteration_respects_explicit_step_iteration_limit():
    result = compute_elastic_step_iteration_limit(
        step={
            "name": "Investigate",
            "stepType": "analysis",
            "stepConfig": {"max_iterations": 4},
        },
        base_limit=4,
        step_tool_history=[
            {"tool_name": "search_jira_tickets", "result": {}},
            {"tool_name": "list_recent_bitbucket_commits", "result": {}},
            {"tool_name": "list_confluence_page_updates", "result": {}},
        ],
        wrapup_forced=False,
        runtime_settings={
            "elastic_iteration_enabled": True,
            "elastic_iteration_max_bonus": 6,
            "elastic_iteration_unique_tool_threshold": 2,
        },
    )

    assert result["bonus"] == 0
    assert result["effective_limit"] == 4
    assert result["reason"] == "explicit_step_limit"


def test_elastic_iteration_respects_strict_runtime_base_limit():
    result = compute_elastic_step_iteration_limit(
        step={"name": "Investigate", "stepType": "analysis"},
        base_limit=2,
        step_tool_history=[
            {"tool_name": "search_jira_tickets", "result": {}},
            {"tool_name": "list_recent_bitbucket_commits", "result": {}},
            {"tool_name": "list_confluence_page_updates", "result": {}},
        ],
        wrapup_forced=False,
        runtime_settings={
            "elastic_iteration_enabled": True,
            "elastic_iteration_max_bonus": 6,
            "elastic_iteration_unique_tool_threshold": 2,
        },
    )

    assert result["bonus"] == 0
    assert result["effective_limit"] == 2
    assert result["reason"] == "strict_base_limit"


def test_get_elastic_iteration_settings_bounds_values():
    result = get_elastic_iteration_settings(
        {
            "elastic_iteration_enabled": True,
            "elastic_iteration_max_bonus": 99,
            "elastic_iteration_unique_tool_threshold": 0,
        }
    )

    assert result == {
        "enabled": True,
        "max_bonus": 12,
        "unique_tool_threshold": 1,
    }
