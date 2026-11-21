"""Shared helpers for the test_tools_github_source_control_* modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.models import CodeRepository, Project
from app.tools.context import ToolContext


async def _create_github_project(db, *, repo_root: str = "/workspace/octryx", policy: dict | None = None) -> str:
    project = Project(name="github-source-control-project", config={}, is_active=True)
    db.add(project)
    await db.flush()
    db.add(
        CodeRepository(
            project_id=project.id,
            name="octryx",
            provider="github",
            repo_root=repo_root,
            remote_url="https://github.com/example/octryx.git",
            default_branch="main",
            config_json={
                "operation_policy": policy
                or {"read": True, "branch": True, "write": True, "pr": True, "index": True, "migration": False}
            },
        )
    )
    await db.commit()
    return project.id


def _github_context(project_id: str, *, db, workspace_root: str | None = None) -> ToolContext:
    return ToolContext(
        user_id="user-1",
        project_ids=[project_id],
        roles=["admin"],
        session_id="session-1",
        db=db,
        workspace_root=workspace_root or str(Path.cwd()),
        project_config={
            "github_url": "https://github.com",
            "github_token": "gh-token",
            "github_allowed_repositories": ["example/octryx"],
            "managed_repo_root": "var/repos/github",
            "tool_policy": {
                "allowlist": [
                    "read_github_file",
                    "list_github_branches",
                    "create_github_branch",
                    "prepare_github_repository",
                    "commit_and_push_github_repository_branch",
                    "get_github_pull_request",
                    "list_github_pull_requests",
                    "create_github_pull_request",
                    "update_github_pull_request",
                    "list_github_issues",
                    "get_github_issue",
                    "create_github_issue",
                    "update_github_issue",
                ]
            },
        },
    )


def _pr_payload(number: int = 7, *, title: str = "PR title", base: str = "main") -> dict[str, Any]:
    return {
        "number": number,
        "title": title,
        "state": "open",
        "user": {"login": "alice"},
        "head": {"ref": "codex/test"},
        "base": {"ref": base},
        "created_at": "2026-07-02T00:00:00Z",
        "updated_at": "2026-07-02T00:00:00Z",
        "html_url": f"https://github.com/example/octryx/pull/{number}",
    }
