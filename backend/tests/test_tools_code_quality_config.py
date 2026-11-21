"""Loading the repository code quality config: project overrides, auto-detected defaults and engineering pack profiles."""

from pathlib import Path

from app.services.code_quality.config import load_repo_code_quality_config
from tests.tools_code_quality_support import _server_pipeline  # noqa: F401


def test_load_repo_code_quality_config_reads_octryx_pyproject(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "pyproject.toml").write_text(
        """
[tool.octryx.code_quality]
linter = "ruff"
formatter = "black"
test_runner = "pytest"
type_checker = "mypy"
        """.strip(),
        encoding="utf-8",
    )

    config = load_repo_code_quality_config(repo)

    assert config["linter"] == "ruff"
    assert config["formatter"] == "black"
    assert config["test_runner"] == "pytest"


def test_load_repo_code_quality_config_merges_project_repo_overrides(tmp_path: Path):
    repo = tmp_path / "acme-orders-api"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "pyproject.toml").write_text(
        """
[tool.octryx.code_quality]
linter = "ruff"
formatter = "black"
test_runner = "pytest"
        """.strip(),
        encoding="utf-8",
    )

    config = load_repo_code_quality_config(
        repo,
        project_config={
            "repo_code_quality": {
                "default": {"coverage_threshold": 85},
                "repos": {
                    "acme-orders-api": {
                        "sast_runners": ["semgrep", "bandit"],
                        "linter": "ruff-check",
                    }
                },
            }
        },
    )

    assert config["linter"] == "ruff-check"
    assert config["formatter"] == "black"
    assert config["coverage_threshold"] == 85
    assert config["sast_runners"] == ["semgrep", "bandit"]
    assert config["project_override_applied"] is True


def test_load_repo_code_quality_config_auto_detects_python_ruff_defaults(tmp_path: Path):
    repo = tmp_path / "python-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8")

    config = load_repo_code_quality_config(repo)

    assert config["language"] == "python"
    assert config["linter"] == "ruff"
    assert config["formatter"] == "ruff"
    assert config["type_checker"] == "mypy"


def test_load_repo_code_quality_config_auto_detects_c_family(tmp_path: Path):
    repo = tmp_path / "c-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\nproject(demo C)\n", encoding="utf-8")
    (repo / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")

    config = load_repo_code_quality_config(repo)

    assert config["language"] == "c"
    assert config["formatter"] == "clang-format"
    assert config["linter"] == "clang-tidy"
    assert config["sast_runners"] == ["semgrep"]


def test_load_repo_code_quality_config_auto_detects_java_openrewrite_defaults(tmp_path: Path):
    repo = tmp_path / "java-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "pom.xml").write_text("<project />", encoding="utf-8")

    config = load_repo_code_quality_config(repo)

    assert config["language"] == "java"
    assert config["refactor_tool"] == "openrewrite"
    assert config["openrewrite_plugin_version"] == "6.37.0"
    assert config["openrewrite_recipes"] == []
    assert config["openrewrite_recipe_artifacts"] == []


def test_load_repo_code_quality_config_applies_engineering_pack_toolchain_defaults(tmp_path: Path):
    repo = tmp_path / "java-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "pom.xml").write_text("<project />", encoding="utf-8")

    config = load_repo_code_quality_config(
        repo,
        project_config={
            "engineering_knowledge_runtime_resolution": {
                "prompt_contract": {"stack_key": "java-spring"},
                "engineering_knowledge_pack": {
                    "pack_id": "pack-1",
                    "version_id": "version-1",
                    "pack_key": "java-21-to-25-spring-boot-34-to-403",
                    "toolchain_policy": {
                        "profiles": {
                            "java-spring": {
                                "openrewrite_recipes": [
                                    "org.openrewrite.java.spring.boot4.UpgradeSpringBoot_4_0"
                                ],
                                "openrewrite_recipe_artifacts": ["org.openrewrite.recipe:rewrite-spring:6.29.0"],
                                "openrewrite_dry_run_required": True,
                                "validation_gates": [{"name": "baseline_tests", "command": "mvn test"}],
                            }
                        }
                    },
                },
            }
        },
    )

    assert config["engineering_knowledge_toolchain_profile_applied"] is True
    assert config["engineering_knowledge_pack_version_id"] == "version-1"
    assert config["openrewrite_recipes"] == ["org.openrewrite.java.spring.boot4.UpgradeSpringBoot_4_0"]
    assert config["openrewrite_recipe_artifacts"] == ["org.openrewrite.recipe:rewrite-spring:6.29.0"]
    assert config["openrewrite_dry_run_required"] is True
    assert config["validation_gates"] == [{"name": "baseline_tests", "command": "mvn test"}]


def test_load_repo_code_quality_config_keeps_repo_local_values_over_pack_defaults(tmp_path: Path):
    repo = tmp_path / "java-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".octryx-codequality.json").write_text(
        """
{
  "language": "java",
  "test_runner": "mvn -Pci test",
  "openrewrite_recipes": ["com.example.RepoLocalRecipe"]
}
""".strip(),
        encoding="utf-8",
    )

    config = load_repo_code_quality_config(
        repo,
        project_config={
            "engineering_knowledge_runtime_resolution": {
                "prompt_contract": {"stack_key": "java-spring"},
                "engineering_knowledge_pack": {
                    "version_id": "version-1",
                    "pack_key": "java-21-to-25-spring-boot-34-to-403",
                    "toolchain_policy": {
                        "profiles": {
                            "java-spring": {
                                "test_runner": "mvn test",
                                "openrewrite_recipes": [
                                    "org.openrewrite.java.spring.boot4.UpgradeSpringBoot_4_0"
                                ],
                                "validation_gates": [{"name": "pack_gate", "command": "mvn verify"}],
                            }
                        }
                    },
                },
            }
        },
    )

    assert config["engineering_knowledge_toolchain_profile_applied"] is True
    assert config["test_runner"] == "mvn -Pci test"
    assert config["openrewrite_recipes"] == ["com.example.RepoLocalRecipe"]
    assert config["validation_gates"] == [{"name": "pack_gate", "command": "mvn verify"}]


def test_load_repo_code_quality_config_applies_non_java_pack_profile_without_openrewrite(tmp_path: Path):
    repo = tmp_path / "python-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8")

    config = load_repo_code_quality_config(
        repo,
        project_config={
            "engineering_knowledge_runtime_resolution": {
                "prompt_contract": {"stack_key": "python"},
                "engineering_knowledge_pack": {
                    "version_id": "python-pack-v1",
                    "pack_key": "python-3.12-quality",
                    "toolchain_policy": {
                        "profiles": {
                            "python": {
                                "type_checker": "pyright",
                                "validation_gates": [{"name": "python_baseline", "command": "pytest -q"}],
                            }
                        }
                    },
                },
            }
        },
    )

    assert config["language"] == "python"
    assert config["engineering_knowledge_toolchain_profile_applied"] is True
    assert config["type_checker"] == "pyright"
    assert config["validation_gates"] == [{"name": "python_baseline", "command": "pytest -q"}]
    assert "refactor_tool" not in config
