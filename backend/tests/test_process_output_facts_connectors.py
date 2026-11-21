"""Connector tools keep subprocess output only as fixed facts or through the named redactor.

Failure paths of git and fixed-operation tools carry a closed code and the exit status, never
the raw stderr/stdout. Output that is the product (a terraform plan, pod logs) is kept, but
without tokens or credentialed URLs.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.models import CodeRepository, Project
from app.tools.connectors import ldap_core, terraform_core
from app.tools.context import ToolContext
from app.tools.kubernetes import GetPodLogs, ListNamespaces
from app.tools.registry import execute_tool

FAKE_TOKEN = "ghp_X6" + "fakeTokenAbcdefghijklmnopqrstuvwxyz0123"
CREDENTIALED_URL = "https://user:tok3n@host/x.git"
INTERNAL_PATH = "/srv/internal/x6-secret-path"
LEAKY_TEXT = f"fatal: auth {FAKE_TOKEN} for {CREDENTIALED_URL} in {INTERNAL_PATH}\n"


def _plain_context(**kwargs) -> ToolContext:
    return ToolContext(user_id="user-1", project_ids=[], roles=["admin"], session_id="session-1", **kwargs)


def _assert_fixed(value: object) -> None:
    text = str(value)
    for marker in (FAKE_TOKEN, "tok3n", INTERNAL_PATH):
        assert marker not in text


def _assert_kept_redacted(value: object) -> None:
    text = str(value)
    assert FAKE_TOKEN not in text
    assert "tok3n" not in text


class _FakeProcess:
    def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._out = (stdout, stderr)

    async def communicate(self, *_args):
        return self._out

    def kill(self) -> None:  # pragma: no cover - timeouts are not exercised
        pass


async def _repository_project(db, *, provider: str, name: str, remote_url: str, repo_root: str) -> str:
    project = Project(name=f"x6-{provider}-facts", config={}, is_active=True)
    db.add(project)
    await db.flush()
    db.add(
        CodeRepository(
            project_id=project.id,
            name=name,
            provider=provider,
            repo_root=repo_root,
            remote_url=remote_url,
            config_json={"operation_policy": {"read": True, "branch": True, "write": True, "pr": True}},
        )
    )
    await db.commit()
    return str(project.id)


@pytest.mark.asyncio
async def test_github_clone_failure_returns_facts_only(db, monkeypatch, tmp_path):
    project_id = await _repository_project(
        db,
        provider="github",
        name="octryx",
        remote_url="https://github.com/example/octryx.git",
        repo_root=str(tmp_path / "var" / "repos" / "github" / "example" / "octryx"),
    )

    async def fake_run_subprocess(command, *, env=None, cwd=None):
        return 128, LEAKY_TEXT, LEAKY_TEXT

    monkeypatch.setattr("app.tools.connectors.github_repository_prepare._run_subprocess", fake_run_subprocess)
    context = ToolContext(
        user_id="user-1",
        project_ids=[project_id],
        roles=["admin"],
        session_id="session-1",
        db=db,
        workspace_root=str(tmp_path),
        project_config={
            "github_url": "https://github.com",
            "github_token": "gh-token",
            "github_allowed_repositories": ["example/octryx"],
            "tool_policy": {"allowlist": ["prepare_github_repository"]},
        },
    )

    result = await execute_tool(
        "prepare_github_repository",
        {"repository": "example/octryx", "base_branch": "main", "branch_name": "codex/x6"},
        context,
    )

    assert result["error_code"] == "git_clone_failed"
    assert result["exit_code"] == 128
    assert "stderr" not in result and "stdout" not in result
    _assert_fixed(result)


@pytest.mark.asyncio
async def test_bitbucket_push_failure_returns_facts_only(db, monkeypatch, tmp_path):
    repo_path = tmp_path / "var" / "repos" / "bitbucket" / "PROJ" / "repo"
    (repo_path / ".git").mkdir(parents=True)
    project_id = await _repository_project(
        db,
        provider="bitbucket",
        name="repo",
        remote_url="https://bitbucket.example/scm/PROJ/repo.git",
        repo_root=str(repo_path),
    )

    async def fake_exec(*args, **kwargs):
        command = list(args)
        if command[:3] == ["git", "status", "--porcelain"]:
            return _FakeProcess(0, b" M README.md\n")
        if command[:3] == ["git", "branch", "--show-current"]:
            return _FakeProcess(0, b"codex/x6\n")
        if command[:2] == ["git", "push"]:
            return _FakeProcess(1, LEAKY_TEXT.encode(), LEAKY_TEXT.encode())
        return _FakeProcess(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    context = ToolContext(
        user_id="test",
        project_ids=[project_id],
        roles=["operator"],
        session_id="test",
        db=db,
        workspace_root=str(tmp_path),
        project_config={
            "bitbucket_url": "https://bitbucket.example",
            "bitbucket_username": "user",
            "bitbucket_password": "secret",
            "bitbucket_allowed_repos": [{"project_key": "PROJ", "repo_slug": "repo", "enabled": True}],
            "tool_policy": {"allowlist": ["commit_and_push_repository_branch"]},
        },
    )

    result = await execute_tool(
        "commit_and_push_repository_branch",
        {"local_path": str(repo_path), "commit_message": "docs: x6"},
        context,
    )

    assert result["error"] == "git push failed"
    assert result["error_code"] == "git_push_failed"
    assert result["exit_code"] == 1
    assert "stderr" not in result and "stdout" not in result
    _assert_fixed(result)


@pytest.mark.asyncio
async def test_kubectl_failure_is_facts_and_pod_logs_are_redacted(monkeypatch):
    context = _plain_context(project_config={"k8s_use_kubectl": True})

    async def failing_kubectl(ctx, args, timeout_sec=20, namespace=None):
        return 1, LEAKY_TEXT, LEAKY_TEXT

    monkeypatch.setattr("app.tools.kubernetes._run_kubectl", failing_kubectl)
    failure = await ListNamespaces().execute({}, context)
    assert failure["error_code"] == "kubectl_command_failed"
    assert failure["exit_code"] == 1
    _assert_fixed(failure)

    async def logs_kubectl(ctx, args, timeout_sec=20, namespace=None):
        return 0, f"GET /ready 200\n{LEAKY_TEXT}", ""

    monkeypatch.setattr("app.tools.kubernetes._run_kubectl", logs_kubectl)
    logs = await GetPodLogs().execute({"namespace": "default", "pod": "api-0"}, context)
    assert "GET /ready 200" in logs["logs"]
    assert INTERNAL_PATH in logs["logs"]
    _assert_kept_redacted(logs)


@pytest.mark.asyncio
async def test_terraform_plan_output_is_kept_redacted_and_error_is_facts(monkeypatch, tmp_path):
    binary = tmp_path / "terraform"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    context = _plain_context(workspace_root=str(tmp_path), project_config={"terraform_binary": str(binary)})
    plan_text = f"Plan: 1 to add, 0 to change.\n{LEAKY_TEXT}"
    outcomes = iter([_FakeProcess(0, plan_text.encode()), _FakeProcess(1, b"", LEAKY_TEXT.encode())])

    async def fake_exec(*args, **kwargs):
        return next(outcomes)

    monkeypatch.setattr(terraform_core.asyncio, "create_subprocess_exec", fake_exec)

    plan = await terraform_core._terraform_run(context, ["plan", "-no-color"])
    assert "Plan: 1 to add" in plan["stdout"]
    _assert_kept_redacted(plan)

    failed = await terraform_core._terraform_run(context, ["plan", "-no-color"])
    assert failed["error"] == "terraform_command_failed exit_code=1"
    assert INTERNAL_PATH in failed["stderr"]
    _assert_kept_redacted(failed)


@pytest.mark.asyncio
async def test_ldap_search_failure_is_facts_and_command_hides_bind_password(monkeypatch, tmp_path):
    binary = tmp_path / "ldapsearch"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    context = _plain_context(
        project_config={
            "ldapsearch_binary": str(binary),
            "ldap_server_url": "ldap://directory.example:389",
            "ldap_bind_dn": "cn=svc,dc=example",
            "ldap_bind_password": FAKE_TOKEN,
        }
    )

    async def fake_exec(*args, **kwargs):
        return _FakeProcess(49, LEAKY_TEXT.encode(), LEAKY_TEXT.encode())

    monkeypatch.setattr(ldap_core.asyncio, "create_subprocess_exec", fake_exec)
    result = await ldap_core._ldap_search(context, base_dn="dc=example", filter_expr="(uid=*)", attrs=["uid"])

    assert result["error"] == "ldap_search_failed exit_code=49"
    assert "stderr" not in result and "stdout" not in result
    assert Path(result["command"].split()[0]) == binary
    _assert_fixed(result)
