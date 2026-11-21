"""Shared helpers for the test_workflow_run_review_* modules."""

from __future__ import annotations

import copy
import subprocess

from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.review.model import ReviewAnswer, ReviewUsage
from tests.phased_workflow_fixtures import PHASE, admin_user, publish_phased, run_workspace

PASS = {"verdict": "pass", "summary": "Correct and tested.", "findings": []}


CHANGES = {"verdict": "changes", "summary": "Rounding still wrong for negatives.",
           "findings": [{"severity": "high", "file": "pay/totals.py", "line": 7, "fix": "Round half away from zero."}]}


class ScriptedReviewer:
    """The governed reviewer model, scripted: records what it was shown."""

    def __init__(self, *answers, during=None):
        self.answers, self.tasks, self.during = list(answers), [], during

    async def factory(self, db, *, project_id, reviewer=None):
        self.reviewer = reviewer
        return self

    async def answer(self, *, system: str, user: str) -> ReviewAnswer:
        self.tasks.append((system, user))
        if self.during is not None:
            await self.during()
        return ReviewAnswer(self.answers.pop(0), ReviewUsage(model="review-model", provider="test", tokens_in=40,
                                                             tokens_out=10))


def _reviewed_definition(max_iterations: int = 1) -> dict:
    work = copy.deepcopy(PHASE)
    return {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start"},
                  {"id": "work", "type": "phase", "label": "Fix", "config": work},
                  {"id": "independent_review", "type": "review", "label": "Independent review"},
                  {"id": "gate", "type": "gate", "config": {"phase": "work", "checks": [
                      {"type": "review_passed", "params": {}, "blocking": True, "description": "Reviewed"},
                      {"type": "tool_called", "params": {"tools": ["knowledge_search"]}, "blocking": True,
                       "description": "Evidence searched"}]}},
                  {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
        "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "work"},
                  {"id": "2", "source_node_id": "work", "target_node_id": "independent_review"},
                  {"id": "3", "source_node_id": "independent_review", "target_node_id": "gate"},
                  {"id": "4", "source_node_id": "gate", "target_node_id": "done", "when": "passed"},
                  {"id": "5", "source_node_id": "gate", "target_node_id": "work", "when": "failed", "kind": "loop",
                   "max_iterations": max_iterations, "label": "Review findings"}],
    }


def changed_repo(path):
    """A git working copy with one uncommitted change (what the reviewer reviews)."""
    path.mkdir(parents=True, exist_ok=True)
    for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=path, check=True)
    (path / "totals.py").write_text("def total(x):\n    return round(x)\n")
    return path


async def _started(db, tmp_path=None):
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    if tmp_path is not None:
        session.metadata_ = {**dict(session.metadata_ or {}), "workspace_root": str(changed_repo(tmp_path / "w"))}
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, _reviewed_definition()),
                          project_id=workspace_id,
                          session=session)
    await db.commit()
    return run, session
