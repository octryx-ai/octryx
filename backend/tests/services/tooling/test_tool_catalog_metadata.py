from app.services.tool_config import get_tool_catalog


def test_tool_catalog_exposes_derived_metadata() -> None:
    entries = {entry["name"]: entry for entry in get_tool_catalog()}

    bash_entry = entries["bash"]
    assert bash_entry["default_connector"] == "system"
    assert bash_entry["enabled"] is True
    assert bash_entry["read_only"] is False
    assert bash_entry["concurrency_safe"] is False
    assert bash_entry["domain_label"] == "execution"
    assert bash_entry["source_label"] == "connector:system"

    mcp_entry = entries["list_mcp_servers"]
    assert mcp_entry["default_connector"] is None
    assert mcp_entry["enabled"] is True
    assert mcp_entry["read_only"] is True
    assert mcp_entry["concurrency_safe"] is True
    assert mcp_entry["domain_label"] == "mcp"
    assert mcp_entry["source_label"] == "mcp_bridge"

    github_entry = entries["list_github_action_runs"]
    assert github_entry["default_connector"] == "github"
    assert github_entry["enabled"] is True
    assert github_entry["domain_label"] == "github"
    assert github_entry["source_label"] == "connector:github"
