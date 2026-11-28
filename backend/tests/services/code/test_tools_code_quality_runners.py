"""Lint and format, OpenRewrite recipes, the Java formatter and multi-language SAST runners."""

from pathlib import Path

import pytest

from app.services.code_quality_service import lint_and_format_workspace, run_openrewrite_recipe, run_sast_suite
from tests.services.code.tools_code_quality_support import _server_pipeline  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_lint_and_format_workspace_uses_ruff_format_for_python(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8")
    (repo / "app.py").write_text("x=1\n", encoding="utf-8")

    monkeypatch.setattr("app.services.code_quality_service._which", lambda command: f"/usr/bin/{command}")

    commands: list[list[str]] = []

    async def fake_run_exec(command, *, cwd, timeout_sec=120, db=None, project_config=None):
        commands.append(command)
        return {"command": command, "exit_code": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr("app.services.code_quality_service._run_exec", fake_run_exec)

    result = await lint_and_format_workspace(cwd=repo, include_sast=False)

    assert result["all_clean"] is True
    assert ["ruff", "check", "."] in commands
    assert ["ruff", "format", "--check", "."] in commands
    assert ["mypy", "."] in commands


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_openrewrite_recipe_builds_maven_command(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "pom.xml").write_text("<project />", encoding="utf-8")

    monkeypatch.setattr("app.services.code_quality_service._which", lambda command: f"/usr/bin/{command}")

    async def fake_run_exec(command, *, cwd, timeout_sec=120, db=None, project_config=None):
        assert cwd == repo
        return {
            "command": command,
            "exit_code": 0,
            "stdout": "Recipe run completed",
            "stderr": "",
            "execution_runtime": {"provider": "host"},
        }

    monkeypatch.setattr("app.services.code_quality_service._run_exec", fake_run_exec)

    result = await run_openrewrite_recipe(
        cwd=repo,
        recipes=["org.openrewrite.java.spring.boot4.UpgradeSpringBoot_4_0"],
        recipe_artifacts=["org.openrewrite.recipe:rewrite-spring:6.29.0"],
    )

    assert result["exit_code"] == 0
    assert result["build_tool"] == "maven"
    assert result["recipes"] == ["org.openrewrite.java.spring.boot4.UpgradeSpringBoot_4_0"]
    assert result["recipe_artifacts"] == ["org.openrewrite.recipe:rewrite-spring:6.29.0"]
    assert result["command"][0] == "mvn"
    assert any(part.startswith("org.openrewrite.maven:rewrite-maven-plugin:6.37.0:run") for part in result["command"])
    assert any(
        part == "-Drewrite.activeRecipes=org.openrewrite.java.spring.boot4.UpgradeSpringBoot_4_0"
        for part in result["command"]
    )


@pytest.mark.asyncio
async def test_run_openrewrite_recipe_blocks_apply_when_pack_requires_dry_run(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "pom.xml").write_text("<project />", encoding="utf-8")

    monkeypatch.setattr("app.services.code_quality_service._which", lambda command: f"/usr/bin/{command}")

    async def fail_if_run_exec(command, *, cwd, timeout_sec=120, db=None, project_config=None):
        raise AssertionError("OpenRewrite should not execute before dry-run")

    monkeypatch.setattr("app.services.code_quality_service._run_exec", fail_if_run_exec)

    result = await run_openrewrite_recipe(
        cwd=repo,
        project_config={
            "engineering_knowledge_runtime_resolution": {
                "prompt_contract": {"stack_key": "java-spring"},
                "engineering_knowledge_pack": {
                    "toolchain_policy": {
                        "profiles": {
                            "java-spring": {
                                "openrewrite_recipes": [
                                    "org.openrewrite.java.spring.boot4.UpgradeSpringBoot_4_0"
                                ],
                                "openrewrite_dry_run_required": True,
                            }
                        }
                    }
                },
            }
        },
    )

    assert result["blocker"]["code"] == "openrewrite_dry_run_required"
    assert result["validation_blockers"][0]["code"] == "openrewrite_dry_run_required"
    assert result["dry_run"] is False
    assert result["recipes"] == ["org.openrewrite.java.spring.boot4.UpgradeSpringBoot_4_0"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_java_formatter_prefers_maven_for_maven_repo(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "pom.xml").write_text("<project />", encoding="utf-8")

    monkeypatch.setattr("app.services.code_quality_service._which", lambda command: f"/usr/bin/{command}")

    async def fake_run_exec(command, *, cwd, timeout_sec=120, db=None, project_config=None):
        return {"command": command, "exit_code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr("app.services.code_quality_service._run_exec", fake_run_exec)

    formatter_result = await lint_and_format_workspace(cwd=repo, include_sast=False)
    formatter_check = next(item for item in formatter_result["checks"] if item["category"] == "formatter")
    assert formatter_check["command"][:3] == ["mvn", "-q", "spotless:check"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_sast_suite_supports_multilanguage_runners(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "package.json").write_text('{"name":"demo","scripts":{"test":"vitest"}}', encoding="utf-8")

    monkeypatch.setattr("app.services.code_quality_service._which", lambda command: f"/usr/bin/{command}")

    async def fake_run_exec(command, *, cwd, timeout_sec=120, db=None, project_config=None):
        return {"command": command, "exit_code": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr("app.services.code_quality_service._run_exec", fake_run_exec)

    result = await run_sast_suite(cwd=repo)

    assert result["all_clean"] is True
    assert result["selected_runners"] == ["semgrep"]
    assert result["checks"][0]["name"] == "semgrep"
