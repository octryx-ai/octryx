"""Resolution of engineering and secure-work tool workspace roots and the approved repository coordinates in the project config patch."""

from __future__ import annotations

from pathlib import Path

from app.agent.core.context.run_context_config import (
    _resolved_engineering_tool_workspace_root,
    _resolved_secure_work_tool_workspace_root,
    _secure_work_project_config_patch,
)


def test_resolved_engineering_tool_workspace_root_requires_registered_ready_repo(tmp_path: Path) -> None:
    repo_root = tmp_path / "acme-orders-access-proxy"
    repo_root.mkdir()

    assert _resolved_engineering_tool_workspace_root(
        {
            "prompt_contract": {"intent": "coding_migration"},
            "repository": {"id": "repo-1", "repo_root": str(repo_root)},
            "blockers": [],
        }
    ) == repo_root.resolve()
    assert _resolved_engineering_tool_workspace_root(
        {
            "prompt_contract": {"intent": "coding_migration"},
            "repository": {"id": "local:repo-1", "repo_root": str(repo_root)},
            "blockers": [],
        }
    ) is None
    assert _resolved_engineering_tool_workspace_root(
        {
            "prompt_contract": {"intent": "coding_migration"},
            "repository": {"id": "repo-1", "repo_root": str(repo_root)},
            "blockers": [{"code": "missing_engineering_knowledge_pack"}],
        }
    ) == repo_root.resolve()
    assert _resolved_engineering_tool_workspace_root(
        {
            "prompt_contract": {"intent": "coding_migration"},
            "repository": {"id": "repo-1", "repo_root": str(repo_root)},
            "blockers": [{"code": "ambiguous_repository"}],
        }
    ) is None


def test_resolved_secure_work_tool_workspace_root_uses_prepared_workspace(tmp_path: Path) -> None:
    workspace_root = tmp_path / "coding-runs" / "OCX-1" / "run-1" / "repo"
    workspace_root.mkdir(parents=True)

    assert _resolved_secure_work_tool_workspace_root(
        {"secure_work_execution_workspace": {"primary_workspace_root": str(workspace_root)}}
    ) == workspace_root.resolve()
    assert _resolved_secure_work_tool_workspace_root({"secure_work_execution_workspace": {}}) is None


def test_secure_work_project_config_patch_exposes_approved_repo_coordinates() -> None:
    patch = _secure_work_project_config_patch(
        {
            "coding_workspace_records": [
                {
                    "project_key": "SHOP",
                    "repository_slug": "aws-shop-infrastructure",
                    "repository_name": "AWS Shop Infrastructure",
                },
                {
                    "project_key": "SHOP",
                    "repository_slug": "aws-shop-infrastructure",
                },
            ]
        }
    )

    assert patch["managed_repo_root"] == "var/repos/bitbucket"
    assert patch["bitbucket_allowed_repos"] == [
        {
            "project_key": "SHOP",
            "repo_slug": "aws-shop-infrastructure",
            "enabled": True,
            "label": "AWS Shop Infrastructure",
            "source": "secure_work_coding_workspace",
        }
    ]
