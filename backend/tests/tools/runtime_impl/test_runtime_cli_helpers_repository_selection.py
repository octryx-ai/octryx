from app.tools.context import ToolContext
from app.tools.runtime_impl import _runtime_cli_helpers as helpers
from app.tools.runtime_impl._runtime_cwd_resolution import _resolve_cwd


def test_select_repository_readme_candidates_prefers_root_then_top_level_then_modules(tmp_path):
    workspace_root = tmp_path
    repo_path = workspace_root / "repo"
    repo_path.mkdir()
    (repo_path / "README.md").write_text("root", encoding="utf-8")

    status_payload = {
        "top_level_directories": [
            {"readme_exists": True, "readme_path": "repo/service/README.md"},
        ],
        "modules": [
            {"readme_exists": True, "readme_path": "repo/module-a/README.md"},
            {"readme_exists": True, "readme_path": "repo/module-b/README.md"},
        ],
    }

    assert helpers._select_repository_readme_candidates(
        repo_path,
        status_payload,
        workspace_root=workspace_root,
    ) == [
        ("repo/README.md", "root_readme"),
        ("repo/service/README.md", "top_level_readme"),
        ("repo/module-a/README.md", "module_readme"),
        ("repo/module-b/README.md", "module_readme"),
    ]


def test_select_repository_code_candidates_prefers_build_files_then_configs(tmp_path):
    workspace_root = tmp_path
    repo_path = workspace_root / "repo"
    (repo_path / "service").mkdir(parents=True)
    (repo_path / ".git").mkdir()
    (repo_path / "node_modules").mkdir()
    (repo_path / "build").mkdir()
    (repo_path / "service" / "package.json").write_text("{}", encoding="utf-8")
    (repo_path / "Dockerfile").write_text("FROM python:3.12", encoding="utf-8")
    (repo_path / "values.yaml").write_text("replicaCount: 1", encoding="utf-8")
    (repo_path / "service" / "chart.yaml").write_text("name: demo", encoding="utf-8")
    (repo_path / "node_modules" / "chart.yaml").write_text("ignored", encoding="utf-8")

    analysis_payload = {
        "build_files": [{"path": "repo/service/package.json"}],
        "top_level_files": ["Dockerfile", "values.yaml"],
    }

    assert helpers._select_repository_code_candidates(
        repo_path,
        analysis_payload,
        workspace_root=workspace_root,
    ) == [
        ("repo/service/package.json", "build_file"),
        ("repo/Dockerfile", "top_level_config"),
        ("repo/values.yaml", "top_level_config"),
        ("repo/service/chart.yaml", "config_or_infra"),
    ]


def test_resolve_cwd_prefers_project_git_root_for_bare_workspace_requests(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".git").mkdir()
    session_workspace = tmp_path / "session"
    session_workspace.mkdir()
    context = ToolContext(
        user_id="user-1",
        project_ids=["project-1"],
        roles=["admin"],
        session_id="session-1",
        project_config={"workspace_root": str(repo_root)},
        db=None,
        workspace_root=str(session_workspace),
    )

    resolved = _resolve_cwd(
        str(session_workspace),
        ".",
        context=context,
        allow_repo_fallback=True,
    )

    assert resolved == repo_root.resolve()


def test_resolve_cwd_allows_missing_relative_paths_inside_single_repo_root(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".git").mkdir()
    session_workspace = tmp_path / "session"
    session_workspace.mkdir()
    context = ToolContext(
        user_id="user-1",
        project_ids=["project-1"],
        roles=["admin"],
        session_id="session-1",
        project_config={"workspace_root": str(repo_root)},
        db=None,
        workspace_root=str(session_workspace),
    )

    resolved = _resolve_cwd(
        str(session_workspace),
        "frontend/chat/src/banner.tsx",
        context=context,
        allow_repo_fallback=True,
        allow_missing=True,
    )

    assert resolved == (repo_root / "frontend/chat/src/banner.tsx").resolve()


def test_resolve_cwd_maps_stale_managed_bitbucket_path_to_session_workspace(tmp_path):
    session_workspace = tmp_path / "session"
    repo_root = session_workspace / "var/repos/bitbucket/SHOP/aws-shop-infrastructure"
    (repo_root / "terraform/base").mkdir(parents=True)
    stale_repo_root = tmp_path / "old-run/octryx/var/repos/bitbucket/SHOP/aws-shop-infrastructure"
    stale_absolute_path = stale_repo_root / "terraform/base"
    (stale_repo_root / ".git").mkdir(parents=True)
    stale_absolute_path.mkdir(parents=True)
    context = ToolContext(
        user_id="user-1",
        project_ids=["project-1"],
        roles=["admin"],
        session_id="session-1",
        project_config={"workspace_root": str(stale_repo_root)},
        db=None,
        workspace_root=str(session_workspace),
    )

    resolved = _resolve_cwd(
        str(session_workspace),
        str(stale_absolute_path),
        context=context,
        allow_repo_fallback=True,
    )

    assert resolved == (repo_root / "terraform/base").resolve()


def test_resolve_cwd_maps_missing_stale_managed_bitbucket_path_to_session_workspace(tmp_path):
    session_workspace = tmp_path / "session"
    repo_root = session_workspace / "var/repos/bitbucket/SHOP/aws-shop-infrastructure"
    (repo_root / "terraform/base").mkdir(parents=True)
    stale_absolute_path = (
        tmp_path
        / "old-run/octryx/var/repos/bitbucket/SHOP/aws-shop-infrastructure/terraform/base/main.tf"
    )
    context = ToolContext(
        user_id="user-1",
        project_ids=["project-1"],
        roles=["admin"],
        session_id="session-1",
        project_config={"workspace_root": str(stale_absolute_path.parents[2])},
        db=None,
        workspace_root=str(session_workspace),
    )

    resolved = _resolve_cwd(
        str(session_workspace),
        str(stale_absolute_path),
        context=context,
        allow_repo_fallback=True,
    )

    assert resolved == (repo_root / "terraform/base/main.tf").resolve()
