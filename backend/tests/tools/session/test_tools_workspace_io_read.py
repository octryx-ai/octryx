"""Listing, reading and analyzing workspace repositories, README status and generation, system context and current time tools."""

import pytest

from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from tests.support.tools_workspace_io_support import _server_pipeline  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_list_and_read_workspace_tools(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# Demo\nHello world\n", encoding="utf-8")
    (repo_dir / "src").mkdir()

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
        workspace_root=str(tmp_path),
    )

    list_result = await execute_tool("list_workspace_directory", {"path": "repo"}, context)
    assert list_result["count"] == 2
    assert [entry["name"] for entry in list_result["entries"]] == ["src", "README.md"]

    read_result = await execute_tool("read_workspace_file", {"path": "repo/README.md"}, context)
    assert read_result["relative_path"] == "repo/README.md"
    assert "Hello world" in read_result["content"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_analyze_workspace_repository_tool(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "readme.md").write_text("# Root\n", encoding="utf-8")
    (repo_dir / "Jenkinsfile").write_text("pipeline {}\n", encoding="utf-8")
    (repo_dir / "corpbuild.xml").write_text("<corpbuild />\n", encoding="utf-8")
    (repo_dir / "pom.xml").write_text(
        "<project><modelVersion>4.0.0</modelVersion><groupId>demo</groupId><artifactId>root-app</artifactId></project>",
        encoding="utf-8",
    )
    module_dir = repo_dir / "service-a"
    module_dir.mkdir()
    source_dir = module_dir / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True)
    (source_dir / "Application.java").write_text("package demo;\nclass Application {}\n", encoding="utf-8")
    resources_dir = module_dir / "src" / "main" / "resources"
    resources_dir.mkdir(parents=True)
    (resources_dir / "application.properties").write_text("server.port=8080\n", encoding="utf-8")
    (module_dir / "pom.xml").write_text(
        "<project><modelVersion>4.0.0</modelVersion><artifactId>service-a</artifactId><packaging>jar</packaging></project>",
        encoding="utf-8",
    )
    (module_dir / "README.md").write_text("# Service A\n\nDetails", encoding="utf-8")

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
        workspace_root=str(tmp_path),
    )

    result = await execute_tool("analyze_workspace_repository", {"path": "repo"}, context)
    assert result["relative_path"] == "repo"
    assert "service-a" in result["top_level_directories"]
    assert any(item["artifact_id"] == "root-app" for item in result["build_files"])
    assert any(item["artifact_id"] == "service-a" for item in result["module_summaries"])
    assert "repo/readme.md" in result["readme_files"]
    assert "repo/service-a/src/main/java/demo/Application.java" in result["source_files"]
    assert "repo/service-a/src/main/resources/application.properties" in result["config_files"]
    assert "repo/Jenkinsfile" in result["ci_files"]
    assert "repo/corpbuild.xml" in result["ci_files"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_list_repository_readme_status_tool(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# Root\n", encoding="utf-8")
    documented = repo_dir / "documented-module"
    documented.mkdir()
    (documented / "pom.xml").write_text(
        "<project><modelVersion>4.0.0</modelVersion><artifactId>documented-module</artifactId></project>",
        encoding="utf-8",
    )
    (documented / "README.md").write_text("# Documented\n", encoding="utf-8")
    undocumented = repo_dir / "undocumented-module"
    undocumented.mkdir()
    (undocumented / "pom.xml").write_text(
        "<project><modelVersion>4.0.0</modelVersion><artifactId>undocumented-module</artifactId></project>",
        encoding="utf-8",
    )

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
        workspace_root=str(tmp_path),
    )

    result = await execute_tool("list_repository_readme_status", {"path": "repo"}, context)
    assert result["relative_path"] == "repo"
    assert any(item["relative_to_repo"] == "undocumented-module" for item in result["missing_module_readmes"])
    assert all(item["relative_to_repo"] != "documented-module" for item in result["missing_module_readmes"])


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_generate_repository_readmes_tool(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "javaagent").mkdir()
    module_dir = repo_dir / "javaagent" / "demo-agent"
    module_dir.mkdir(parents=True)
    (module_dir / "pom.xml").write_text(
        "<project><modelVersion>4.0.0</modelVersion><groupId>demo</groupId><artifactId>demo-agent</artifactId><packaging>jar</packaging></project>",
        encoding="utf-8",
    )
    (module_dir / "src" / "main" / "java").mkdir(parents=True)
    (module_dir / "src" / "main" / "java" / "DemoAgent.java").write_text("class DemoAgent {}", encoding="utf-8")

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
        workspace_root=str(tmp_path),
    )
    result = await execute_tool("generate_repository_readmes", {"path": "repo"}, context)
    assert result["missing_after_write_count"] == 0
    assert (repo_dir / "README.md").exists()
    assert (repo_dir / "javaagent" / "README.md").exists()
    assert (module_dir / "README.md").exists()
    root_text = (repo_dir / "README.md").read_text(encoding="utf-8")
    module_text = (module_dir / "README.md").read_text(encoding="utf-8")
    assert "## Development workflow" in root_text
    assert "## Making changes" in module_text
    assert "## Important entry points" in module_text


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_get_system_context_tool():
    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
        workspace_root="/srv/octryx",
    )
    result = await execute_tool("get_system_context", {}, context)
    assert result["workspace_root"] == "/srv/octryx"
    assert "os_name" in result
    assert "command_hints" in result


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_get_current_time_tool():
    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
    )
    result = await execute_tool("get_current_time", {"relative_days": -5}, context)
    assert result["relative_days"] == -5
    assert "local_date" in result
    assert "target_local_date" in result
    assert "utc_time_iso" in result
    assert "target_utc_time_iso" in result
