"""Package roots keep only their markers and aggregates, and service packages keep stable exports."""

from __future__ import annotations

from tests.package_layout_support import _repo_root


def test_tools_root_private_helpers_stay_underscore_prefixed() -> None:
    root = _repo_root() / "app" / "tools"
    private_helpers = sorted(path.name for path in root.glob("_*.py") if path.name != "__init__.py")
    assert private_helpers, "tools root should keep private helper modules underscore-prefixed"
    assert all(name.startswith("_") for name in private_helpers)


def test_models_root_contains_only_aggregate_modules() -> None:
    """Keep leaf model implementations inside domain packages instead of app.models root."""

    root = _repo_root() / "app" / "models"
    allowed_root_model_modules = {"__init__.py", "json_text.py"}

    for path in root.glob("*.py"):
        assert path.name in allowed_root_model_modules, (
            f"{path.as_posix()} should live in a models domain package instead of app.models root."
        )


def test_middleware_root_contains_only_package_marker() -> None:
    """Keep middleware implementations grouped in subpackages instead of root files."""

    root = _repo_root() / "app" / "middleware"
    allowed_root_modules = {"__init__.py"}

    for path in root.glob("*.py"):
        assert path.name in allowed_root_modules, (
            f"{path.as_posix()} should live in a middleware subgroup package instead of app.middleware root."
        )


def test_plugins_root_contains_only_package_marker() -> None:
    """Keep plugin implementations grouped in core/channels/mcp packages instead of root files."""

    root = _repo_root() / "app" / "plugins"
    allowed_root_modules = {"__init__.py"}

    for path in root.glob("*.py"):
        assert path.name in allowed_root_modules, (
            f"{path.as_posix()} should live in a plugin subgroup package instead of app.plugins root."
        )


def test_scheduler_root_contains_only_package_marker() -> None:
    """Keep scheduler implementations grouped in dispatch/execution/output/tickets packages."""

    root = _repo_root() / "app" / "scheduler"
    allowed_root_modules = {"__init__.py"}

    for path in root.glob("*.py"):
        assert path.name in allowed_root_modules, (
            f"{path.as_posix()} should live in a scheduler subgroup package instead of app.scheduler root."
        )


def test_service_package_exports_stay_stable() -> None:
    import app.services.code_intelligence as code_intelligence
    import app.services.office as office
    import app.services.session as session
    import app.services.system_config as system_config

    assert code_intelligence.__all__ == [
        "_build_snapshot",
        "get_code_graph_admin_status",
        "get_repository_snapshot",
        "graph",
        "graph_admin",
        "graph_analytics",
        "graph_context",
        "graph_queries",
        "graph_query_support",
        "indexing",
        "outline",
        "outline_queries",
        "process",
        "queries",
        "repository",
        "run_code_index",
        "semantic_build",
        "semantic_store",
        "structure",
        "symbol_analysis",
    ]
    assert office.__all__ == ["ai_template", "documents", "render", "storage", "template", "template_package"]
    assert session.__all__ == [
        "api",
        "collaboration",
        "entity",
        "run_state",
        "stream",
        "tool_cache",
        "workspace",
        "workspace_restore",
        "workspace_storage",
        "workspace_sync",
    ]

    assert "AGENT_AUTH_LOGIN_MODE_KEY" in system_config.__all__
    assert "get_agent_runtime_settings" in system_config.__all__
