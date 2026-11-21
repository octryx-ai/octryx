"""Shared helpers for the test_workflow_run_succession_* modules."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

from app.models.runtime.secure_work import WorkItem
from app.services.workflow_runs import platform_actions
from app.services.workflow_runs.platform import dispatch as dispatch_module
from app.services.workflow_runs.platform import jira, pr_adoption, scm
from app.services.workflow_runs.platform.dispatch import read_outcome
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.phased_workflow_fixtures import admin_user, run_workspace

REPOSITORY = "github:acme/payments"


class Tools:
    """The governed tool dispatch, scripted per tool; ``answers[tool]`` is a queue (the last answer repeats)."""

    def __init__(self, monkeypatch, answers: dict[str, list[dict]]):
        self.calls: list[tuple[str, dict]] = []
        self.answers = answers

        async def dispatch(db, run, tool, arguments, *, capability_class):
            self.calls.append((tool, arguments))
            queue = self.answers.get(tool) or [{"status": "ok"}]
            return read_outcome(queue.pop(0) if len(queue) > 1 else queue[0])

        for module in (dispatch_module, jira, scm, pr_adoption, platform_actions):
            monkeypatch.setattr(module, "dispatch_tool", dispatch, raising=False)

    def tools(self) -> list[str]:
        return [call[0] for call in self.calls]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={"GIT_CONFIG_NOSYSTEM": "1", "HOME": str(cwd), "PATH": "/usr/bin:/bin:/usr/local/bin",
                               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                               "GIT_COMMITTER_EMAIL": "t@t"}).stdout.strip()


def _origin(tmp_path: Path) -> tuple[Path, Path]:
    """A bare origin with ``main`` and a clone of it (the prepared working copy)."""
    origin, seed, work = tmp_path / "origin.git", tmp_path / "seed", tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(seed))
    (seed / "README.md").write_text("payments\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "init")
    _git(seed, "push", "-q", "origin", "HEAD:main")
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    return seed, work


def _remote_branch(seed: Path, work: Path, name: str, *, foreign_commit: bool = False) -> str:
    _git(seed, "checkout", "-q", "-B", name, "origin/main")
    if foreign_commit:
        (seed / "other.txt").write_text("someone else\n")
        _git(seed, "add", "-A")
        _git(seed, "commit", "-q", "-m", "foreign")
    _git(seed, "push", "-q", "-f", "origin", f"{name}:{name}")
    _git(work, "fetch", "-q", "--prune", "origin")
    return _git(seed, "rev-parse", "HEAD")


def _definition(*actions: tuple[str, str, dict]) -> dict:
    """start → actions in order → a conversation that waits; every failure → the action_failed pause → blocked."""
    nodes = [{"id": "start", "type": "start"}]
    edges = []
    previous = "start"
    for node_id, action, params in actions:
        nodes.append({"id": node_id, "type": "platform_action", "label": node_id,
                      "config": {"action": action, "params": params}})
        edges.append({"id": f"to-{node_id}", "source_node_id": previous, "target_node_id": node_id,
                      **({"when": "succeeded"} if previous != "start" else {})})
        edges.append({"id": f"{node_id}-ko", "source_node_id": node_id, "target_node_id": "action_failed",
                      "when": "failed"})
        previous = node_id
    nodes += [{"id": "hold", "type": "user_conversation", "config": {"question": "Anything else?"}},
              {"id": "action_failed", "type": "pause", "config": {"reason": "action_failed"}},
              {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
              {"id": "blocked", "type": "outcome", "config": {"outcome": "blocked"}}]
    edges += [{"id": "to-hold", "source_node_id": previous, "target_node_id": "hold", "when": "succeeded"},
              {"id": "hold-done", "source_node_id": "hold", "target_node_id": "done"},
              {"id": "failed-blocked", "source_node_id": "action_failed", "target_node_id": "blocked"}]
    return {"execution_kind": "phased", "nodes": nodes, "edges": edges}


BRANCH = _definition(("branch", "scm.create_branch", {"branch_type": "feature"}))


async def _item(db, *, source_type: str = "jira") -> WorkItem:
    item = WorkItem(source_type=source_type, source_instance="test", source_key=f"BRD-{uuid.uuid4().hex[:4].upper()}",
                    source_project_key="BRD", title="Add a slugify function to textkit", work_state="development")
    db.add(item)
    await db.flush()
    return item


async def _start(db, key: str, item: WorkItem, **extra):
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin, item.id)
    session = await new_chat_session(db, admin, workspace_id)
    return await start_run(db, user=admin, workflow_key=key, project_id=workspace_id, session=session,
                           work_item_id=item.id, repository=REPOSITORY, **extra)


def _name(item: WorkItem) -> str:
    return f"feature/{item.source_key}-add-a-slugify-function-to-textkit"


EXISTS = {"error": "Branch already exists", "status_code": 422}
