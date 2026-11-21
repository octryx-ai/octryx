"""A push to a read-only repository (directly, by push URL or mirror upstream) is refused before commit, and a registered repository satisfies the workspace tools and the repository operation policy."""

from __future__ import annotations

from pathlib import Path

from app.tools.bitbucket_impl import _bitbucket_sync_repo
from app.tools.bitbucket_impl._bitbucket_sync_repo import CommitAndPushRepositoryBranch
from tests.bitbucket_repository_access_gate_support import BASE, CLONE, _context, _register, _workspace
from tests.knowledge_evidence_seed_support import seed_workspace

# --- git push ---------------------------------------------------------------------------------------------------


class FakeGit:
    """``_run_git`` of the push tool: each working copy's ``origin`` URLs (fetch and push), every command recorded."""

    def __init__(self, origins: dict[Path, dict[str, list[str]]]) -> None:
        self.origins = {str(path): urls for path, urls in origins.items()}
        self.commands: list[list[str]] = []

    def ran(self, *prefix: str) -> bool:
        return any(command[:len(prefix)] == list(prefix) for command in self.commands)

    async def __call__(self, command, *, cwd=None, timeout_sec=90, env=None):
        self.commands.append(list(command))
        if command[:3] == ["git", "remote", "get-url"]:
            urls = self.origins.get(str(cwd))
            if urls is None:
                return 2, "", "error: No such remote 'origin'"
            return 0, "\n".join(urls["push" if "--push" in command else "fetch"]) + "\n", ""
        if command[:3] == ["git", "status", "--porcelain"]:
            return 0, " M README.md\n", ""
        if command[:3] == ["git", "branch", "--show-current"]:
            return 0, "feature/x\n", ""
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return 0, "abc123\n", ""
        return 0, "", ""


def _working_copy(tmp_path: Path) -> Path:
    repo = tmp_path / "app"
    (repo / ".git").mkdir(parents=True)
    return repo


async def _push(db, tmp_path, monkeypatch, mode: str | None, origins) -> tuple[dict, FakeGit]:
    repo = _working_copy(tmp_path)
    workspace_id = await _workspace(db, repo_root=str(repo))
    if mode is not None:
        await _register(db, workspace_id, mode)
    git = FakeGit(origins(repo))
    monkeypatch.setattr(_bitbucket_sync_repo, "_run_git", git)
    context = _context(db, workspace_id, workspace_root=str(tmp_path))
    result = await CommitAndPushRepositoryBranch().execute(
        {"local_path": str(repo), "commit_message": "change", "repo_slug": "app"}, context)
    return result, git


def _plain_origin(url: str = CLONE):
    return lambda repo: {repo: {"fetch": [url], "push": [url]}}


async def test_a_push_to_a_read_only_repository_is_refused_before_commit_and_push(db, tmp_path, monkeypatch):
    result, git = await _push(db, tmp_path, monkeypatch, "read_only",
                              _plain_origin("https://bot:pw@bitbucket.example.test/bitbucket/scm/PROJ/app.git"))

    assert (result["code"], result["project_key"], result["repo_slug"]) == ("repository_read_only", "PROJ", "app")
    assert not git.ran("git", "push") and not git.ran("git", "commit") and not git.ran("git", "add")


async def test_a_push_to_a_read_write_repository_proceeds(db, tmp_path, monkeypatch):
    result, git = await _push(db, tmp_path, monkeypatch, "read_write", _plain_origin())

    assert result["status"] == "pushed"
    assert git.ran("git", "commit") and git.ran("git", "push", "--set-upstream", "origin", "feature/x")


async def test_a_push_to_an_unregistered_repository_proceeds_as_today(db, tmp_path, monkeypatch):
    result, git = await _push(db, tmp_path, monkeypatch, None, _plain_origin())

    assert result["status"] == "pushed"
    assert git.ran("git", "push", "--set-upstream", "origin", "feature/x")


async def test_a_push_url_or_a_mirror_upstream_naming_the_read_only_repository_is_refused(db, tmp_path, monkeypatch):
    other = f"{BASE}/scm/PROJ/other.git"
    result, git = await _push(db, tmp_path, monkeypatch, "read_only",
                              lambda repo: {repo: {"fetch": [other], "push": [CLONE]}})
    assert result["code"] == "repository_read_only", "origin's pushurl is where git push goes"
    assert not git.ran("git", "push")

    mirror = tmp_path / "mirror.git"
    mirror.mkdir()
    (mirror / "HEAD").write_text("ref: refs/heads/main\n")
    result, git = await _push(db, tmp_path / "second", monkeypatch, "read_only",
                              lambda repo: {repo: {"fetch": [str(mirror)], "push": [str(mirror)]},
                                            mirror: {"fetch": [CLONE], "push": [CLONE]}})
    assert result["code"] == "repository_read_only", "the upstream push from the platform mirror is chased"
    assert not git.ran("git", "push")


async def test_a_registered_repository_is_allowed_for_the_workspaces_bitbucket_tools(db):
    """scm.create_branch accepts a registered repository, not only the ``bitbucket_allowed_repos`` list. The
    Workspace config lists it."""
    from app.services.project.service import get_project_config

    workspace_id = await seed_workspace(db)
    before = await get_project_config(workspace_id, db)
    assert not any(entry.get("repo_slug") == "app" for entry in before.get("bitbucket_allowed_repos") or []
                   if isinstance(entry, dict))
    await _register(db, workspace_id, "read_write")
    after = await get_project_config(workspace_id, db)
    assert {"project_key": "PROJ", "repo_slug": "app", "source": "registered"} in after["bitbucket_allowed_repos"]


async def test_a_registered_repository_satisfies_the_repository_operation_policy(db):
    """A branch on a registered read_write repository is not refused as "not configured for this project/provider"
    (not only code_repositories count). The registration's access mode decides."""
    from fastapi import HTTPException

    from app.services.project_resource_policy import require_project_repository_operation

    async def allowed(workspace_id: str, operation: str) -> bool:
        try:
            await require_project_repository_operation(db, project_ids=[workspace_id], provider="bitbucket",
                                                       operation=operation, repository_refs=["PROJ/app"])
        except HTTPException:
            return False
        return True

    unregistered = await seed_workspace(db)
    assert not await allowed(unregistered, "read")
    writer = await seed_workspace(db)
    await _register(db, writer, "read_write")
    assert await allowed(writer, "branch") and await allowed(writer, "pr")
    reader = await seed_workspace(db)
    await _register(db, reader, "read_only")
    assert await allowed(reader, "read") and not await allowed(reader, "branch")
