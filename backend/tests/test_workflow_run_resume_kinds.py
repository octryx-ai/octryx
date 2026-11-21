"""Every pause goes on the way it names (``detail.resume.kind``), or the decision is refused: never a silent "running".

A ``continue`` on an ``action_failed`` pause (resume kind ``retry_action``) must not fall into ``_resume``'s
fallback, which sets the run running at the pause node while nothing ever enters the failed ``scm.create_branch``
step again.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.models.runtime.secure_work import WorkItem
from app.services.workflow_runs.actions import perform_action
from app.services.workflow_runs.pause import RESUME_KINDS, _resume
from app.services.workflow_runs.platform import scm
from app.services.workflow_runs.records import WorkflowRunError
from tests.phased_workflow_fixtures import admin_user
from tests.test_workflow_run_platform_actions import _run as start
from tests.workflow_run_succession_support import BRANCH, Tools, _origin

SERVICES = Path(__file__).resolve().parents[1] / "app" / "services"
_RESUME_KIND = re.compile(r'"resume"\s*:\s*\{\s*"kind"\s*:\s*([^,}]+)')
_PAUSE_RUN = re.compile(r"(?<!def )\bpause_run\(")


def _calls(text: str, start_at: int) -> str:
    depth = 0
    for index in range(start_at, len(text)):
        depth += {"(": 1, ")": -1}.get(text[index], 0)
        if depth == 0 and text[index] == ")":
            return text[start_at:index + 1]
    return text[start_at:]


def test_every_pause_source_names_a_resume_kind_that_resume_knows():
    """A guard over the code: every ``"resume": {"kind": ...}`` literal (also both sides of a conditional) is in
    ``RESUME_KINDS``, and every ``pause_run`` call names a resume."""
    seen: set[str] = set()
    missing: list[str] = []
    for path in SERVICES.rglob("*.py"):
        text = path.read_text()
        for match in _RESUME_KIND.finditer(text):
            seen.update(re.findall(r'"([a-z_]+)"', match.group(1)))
        for match in _PAUSE_RUN.finditer(text):
            if '"resume"' not in _calls(text, match.end() - 1):
                missing.append(f"{path.relative_to(SERVICES)}:{text[:match.start()].count(chr(10)) + 1}")
    assert seen and seen <= RESUME_KINDS, sorted(seen - RESUME_KINDS)
    assert missing == [], missing


@pytest.mark.asyncio
async def test_an_unknown_resume_kind_is_refused_and_the_run_stays_paused(db):
    from app.models import WorkflowRun

    run = WorkflowRun(workflow_key="w", status="paused", pause_reason="action_failed", current_node_id="pause")
    with pytest.raises(WorkflowRunError) as refused:
        await _resume(db, run, {"kind": "teleport"}, actor_id="u")
    assert refused.value.code == "unknown_resume" and refused.value.status_code == 409
    assert (run.status, run.pause_reason) == ("paused", "action_failed")


@pytest.mark.asyncio
async def test_continue_on_a_failed_action_runs_the_step_again(db, monkeypatch, tmp_path):
    _seed, work = _origin(tmp_path)
    tools = Tools(monkeypatch, {"create_github_branch": [{"status": "created"}],
                                "prepare_github_repository": [{"local_path": str(work), "base_branch": "main"}]})
    real_create = scm.create_branch
    failed: list[bool] = []

    async def pull_fails_once(db, run, params):
        if not failed:
            failed.append(True)
            raise RuntimeError("git pull failed")
        return await real_create(db, run, params)

    monkeypatch.setattr(scm, "create_branch", pull_fails_once)
    item = WorkItem(source_type="jira", source_instance="test", source_key="BRD-11", source_project_key="BRD",
                    title="Add a slugify function", work_state="development")
    db.add(item)
    await db.flush()
    run = await start(db, BRANCH, repository="github:acme/payments", work_item_id=item.id)
    assert (run.status, run.pause_reason) == ("paused", "action_failed")

    await perform_action(db, run, user=await admin_user(db), body={"action": "continue", "k": 1})
    assert (run.status, run.branch) == ("waiting", "feature/BRD-11-add-a-slugify-function")
    assert tools.tools().count("create_github_branch") == 1
