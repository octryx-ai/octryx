"""The reviewer knows what the pipeline needs: a review must not ask to remove the environment file's
venv/Playwright setup the system tests need."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.workflow_runs.review.model import ReviewAnswer, ReviewUsage
from app.services.workflow_runs.review.pipeline_needs import PIPELINE_NEEDS_RULE, declared


def _pipeline(file: str) -> dict:
    return {"pipeline": {"audit": {"source": "environment_file", "file": file, "app_folder": "app",
                                   "commands": ["flutter test", "python system_test/run_system_test.py"]}}}


def test_the_declared_environment_names_the_commands_and_the_file(tmp_path: Path):
    (tmp_path / "app" / ".octryx").mkdir(parents=True)
    (tmp_path / "app" / ".octryx" / "environment.json").write_text(json.dumps(
        {"setup": ["python -m venv .venv", ".venv/bin/pip install playwright"], "test": "flutter test"}))

    class Run:
        context = _pipeline("app/.octryx/environment.json")

    text = declared(Run(), tmp_path)
    assert "python system_test/run_system_test.py" in text and ".venv/bin/pip install playwright" in text
    Run.context = {}
    assert declared(Run(), tmp_path) == ""


@pytest.mark.asyncio
async def test_the_reviewer_gets_the_pipelines_environment_and_the_rule(db, tmp_path):
    from app.services.workflow_runs.review.runner import run_due_reviews
    from tests.review_convergence_support import _delivery, _started
    from tests.test_workflow_run_pause import _turn

    run, session = await _started(db, tmp_path, _delivery(tmp_path, {"tasks": False, "auto_revise": 0}, {}))
    root = Path(session.metadata_["workspace_root"])
    (root / "app" / ".octryx").mkdir(parents=True)
    (root / "app" / ".octryx" / "environment.json").write_text(json.dumps({"setup": ["python -m venv .venv"]}))
    await _turn(db, session.id, ["knowledge_search"])
    run.context = {**dict(run.context or {}), "local_path": str(root), **_pipeline("app/.octryx/environment.json")}
    await db.commit()
    asked = []

    class Reviewer:
        async def factory(self, db, *, project_id, reviewer=None):
            return self

        async def answer(self, *, system, user, images=None):
            asked.append((system, user))
            return ReviewAnswer({"verdict": "pass", "summary": "ok", "findings": []},
                                ReviewUsage(model="m", tokens_in=1, tokens_out=1))

    assert await run_due_reviews(db, model_factory=Reviewer().factory) == 1
    system, user = asked[0]
    assert PIPELINE_NEEDS_RULE in system
    assert "python -m venv .venv" in user and "python system_test/run_system_test.py" in user
