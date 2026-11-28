"""Tests for git intelligence, workspace repository management, and file operations."""

from pathlib import Path

import pytest

from app.services.repository_bootstrap import ensure_workspace_repository
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


def _write_fake_ansible_binaries(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    inventory_path = tmp_path / "hosts.ini"
    inventory_path.write_text("[web]\nweb01\n", encoding="utf-8")

    inventory_binary = tmp_path / "ansible-inventory"
    inventory_binary.write_text(
        """#!/usr/bin/env python3
import json
print(json.dumps({"web": {"hosts": ["web01"]}, "_meta": {"hostvars": {"web01": {"ansible_host": "10.0.0.1"}}}}))
""",
        encoding="utf-8",
    )
    inventory_binary.chmod(0o755)

    ansible_binary = tmp_path / "ansible"
    ansible_binary.write_text(
        """#!/usr/bin/env python3
import json
import pathlib
import sys

args = sys.argv[1:]
tree_dir = pathlib.Path(args[args.index("--tree") + 1])
tree_dir.mkdir(parents=True, exist_ok=True)
(tree_dir / "web01").write_text(json.dumps({"ansible_facts": {"ansible_hostname": "web01", "ansible_os_family": "Debian"}}))
print("web01 | SUCCESS => gathered")
""",
        encoding="utf-8",
    )
    ansible_binary.chmod(0o755)

    playbook_binary = tmp_path / "ansible-playbook"
    playbook_binary.write_text(
        """#!/usr/bin/env python3
import sys
args = sys.argv[1:]
if "--check" in args:
    print("PLAY RECAP: web01 changed=0 unreachable=0 failed=0")
else:
    print("PLAY RECAP: web01 changed=2 unreachable=0 failed=0")
""",
        encoding="utf-8",
    )
    playbook_binary.chmod(0o755)

    playbook_root = tmp_path / "playbooks"
    playbook_root.mkdir()
    (playbook_root / "deploy.yml").write_text("- hosts: all\n  tasks: []\n", encoding="utf-8")
    return inventory_path, inventory_binary, ansible_binary, playbook_binary


@pytest.mark.asyncio
async def test_ensure_workspace_repository_initializes_local_git_repo(tmp_path: Path):
    result = await ensure_workspace_repository(
        workspace_root=tmp_path,
        project_config={},
        session_id="session-1",
        reason="write",
    )

    assert result["status"] == "bootstrapped"
    assert result["provider"] == "local"
    assert (tmp_path / ".git").exists()
    assert (tmp_path / "README.md").exists()
    assert (tmp_path / ".gitignore").exists()


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_write_workspace_file_bootstraps_repo_before_write(tmp_path: Path):
    context = ToolContext(
        user_id="user-1",
        project_ids=[],
        roles=["admin"],
        session_id="session-1",
        project_config={},
        workspace_root=str(tmp_path),
    )

    result = await execute_tool(
        "write_workspace_file",
        {"path": "src/main.py", "content": "print('hello')"},
        context,
    )

    assert result["path"].endswith("src/main.py")
    assert (tmp_path / ".git").exists()
    assert (tmp_path / "src" / "main.py").read_text(encoding="utf-8") == "print('hello')\n"
    assert result["repository_bootstrap"]["status"] in {"bootstrapped", "existing"}


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_ensure_workspace_repository_uses_github_provider(monkeypatch, tmp_path: Path):
    async def fake_create_github_repository(*, project_config, config, repo_name):
        return {
            "provider": "github",
            "repository_name": repo_name,
            "full_name": f"acme/{repo_name}",
            "html_url": f"https://github.com/acme/{repo_name}",
            "clone_url": f"https://github.com/acme/{repo_name}.git",
            "git_env": {"GIT_CONFIG_VALUE_1": "Authorization: Basic header"},
        }

    async def fake_initialize_local_repository(**kwargs):
        repo_path = kwargs["repo_path"]
        repo_path.mkdir(parents=True, exist_ok=True)
        (repo_path / ".git").mkdir()
        return {
            "initialized": True,
            "commit_created": True,
            "written_files": [],
            "head_commit": "abc123",
        }

    monkeypatch.setattr(
        "app.services.repository_bootstrap.service.create_github_repository",
        fake_create_github_repository,
    )
    monkeypatch.setattr(
        "app.services.repository_bootstrap.service.initialize_local_repository",
        fake_initialize_local_repository,
    )

    result = await ensure_workspace_repository(
        workspace_root=tmp_path,
        project_config={
            "repository_bootstrap": {
                "provider": "github",
                "github_owner": "acme",
                "github_owner_type": "org",
            }
        },
        session_id="session-2",
        reason="write",
    )

    assert result["status"] == "bootstrapped"
    assert result["provider"] == "github"
    assert result["remote"]["full_name"] == "acme/workspace"
