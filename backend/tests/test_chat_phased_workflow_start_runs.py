"""Run outcomes of the phased start: phone answers, committing first steps, refused starts, retry hints, device targets and budgets."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Session as ChatSession
from app.models import WorkItem
from tests.chat_phased_workflow_start_support import _answer, _items, _record, _send, _workspace, fakes  # noqa: F401

pytestmark = pytest.mark.workflow_proposals


def test_the_phone_answers_a_held_workflow_proposal_but_reaches_no_other_chat_or_workflow_write():
    from app.services.mobile.session import phone_may_use

    allowed = [("POST", "/chat/api/sessions/s1/workflow-proposal"), ("GET", "/chat/api/workflows"),
               ("GET", "/api/v1/workflow-runs/runtime-targets")]
    refused = [("GET", "/chat/api/sessions/s1/workflow-proposal"), ("POST", "/chat/api/workflows"),
               ("PUT", "/chat/api/workflows"), ("POST", "/chat/api/sessions/s1/workflow-proposal/extra"),
               ("POST", "/chat/api/sessions/s1/rename"), ("DELETE", "/chat/api/sessions/s1"),
               ("POST", "/chat/api/workflows/spec-writing"), ("POST", "/api/v1/workflow-runs/runtime-targets")]
    assert all(phone_may_use(method, path) for method, path in allowed)
    assert not any(phone_may_use(method, path) for method, path in refused)


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_a_run_whose_first_step_commits_starts_and_answers(client, db, auth_headers, fakes):  # noqa: F811
    """A run started inside a savepoint would be closed by the branch tool's connection-health commit: the Allow
    would answer 500 and the run hang at ``branch``."""
    state = fakes("spec-writing")
    state["commit_inside"] = True
    project_id = await _workspace(db)
    session_id = await _send(client, auth_headers, project_id=project_id)
    proposal_id = (await _record(db, session_id))["proposal_id"]

    response = await _answer(client, auth_headers, session_id, proposal_id, "apply")
    assert response.status_code == 200, response.text
    [started] = state["started"]
    record = await _record(db, session_id)
    assert record["started"]["run_id"] and record["started"]["session_id"] == started["session_id"]


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_a_refused_start_leaves_no_chat_session_without_its_run(client, db, auth_headers, fakes):  # noqa: F811
    state = fakes("spec-writing")
    state["refuse_run"] = "A build workflow never runs on the server."
    project_id = await _workspace(db)
    session_id = await _send(client, auth_headers, project_id=project_id)
    proposal_id = (await _record(db, session_id))["proposal_id"]

    assert (await _answer(client, auth_headers, session_id, proposal_id, "apply")).status_code == 200
    db.expire_all()
    sessions = (await db.execute(select(ChatSession.id).where(ChatSession.project_id == project_id))).scalars().all()
    assert sessions == [session_id]


def test_the_retry_hint_is_added_once_also_to_an_error_kept_before_the_hint():
    """Octryx naming: ``started.error`` carries the assistant message's retry words, never twice."""
    from app.services.workflow_routing.phased_start_run import _retry_hint

    assert _retry_hint("No repository.") == "No repository. Press Start again to retry."
    assert _retry_hint("No repository. Press Start again to retry.") == "No repository. Press Start again to retry."


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_a_card_model_needs_a_device_location(client, db, auth_headers, fakes):  # noqa: F811
    """The chat start card carries the model for a device run; on the Server it is
    refused before anything starts."""
    state = fakes("spec-writing")
    project_id = await _workspace(db)
    session_id = await _send(client, auth_headers, project_id=project_id)
    proposal_id = (await _record(db, session_id))["proposal_id"]
    refused = await _answer(client, auth_headers, session_id, proposal_id, "apply", run_on="server",
                            model="claude-sonnet-5-5")
    assert refused.status_code == 422
    alone = await _answer(client, auth_headers, session_id, proposal_id, "apply", model="claude-sonnet-5-5")
    assert alone.status_code == 422
    assert not state.get("started")


@pytest.mark.asyncio
async def test_the_cards_model_goes_into_a_device_target(monkeypatch):
    from app.services.workflow_routing import phased_start_run
    from app.services.workflow_runs.runtime_target import target as target_module

    device = {"kind": "device", "device_id": "d1", "folder": "/w", "profile": "seat"}

    async def options(db, *, user):
        return [{"key": "dev", "target": device}, {"key": "server", "target": {"kind": "server"}}]

    monkeypatch.setattr(target_module, "target_options", options)
    chosen = await phased_start_run._chosen_target(None, None, {"run_on": {"chosen": "dev", "model": "gpt-6.1-sol"}})
    assert chosen == {**device, "model": "gpt-6.1-sol"}
    server = await phased_start_run._chosen_target(None, None, {"run_on": {"chosen": "server", "model": "x"}})
    assert server == {"kind": "server"}
    plain = await phased_start_run._chosen_target(None, None, {"run_on": {"chosen": "dev"}})
    assert plain == device


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_the_cards_budget_lands_on_the_new_epic_before_its_run_and_its_stories_inherit_it(
        client, db, auth_headers, fakes):  # noqa: F811
    """A new epic gets an item to set the budget on before the start."""
    from app.services.workflow_runs.limits import inherited_budget

    state = fakes("spec-writing")
    project_id = await _workspace(db)
    session_id = await _send(client, auth_headers, project_id=project_id)
    proposal_id = (await _record(db, session_id))["proposal_id"]
    bad = await _answer(client, auth_headers, session_id, proposal_id, "apply", budget={"cost_usd": -1})
    assert bad.status_code == 422 and state["started"] == []

    response = await _answer(client, auth_headers, session_id, proposal_id, "apply", budget={"cost_usd": 15})
    assert response.status_code == 200, response.text
    [item] = await _items(db, project_id)
    await db.refresh(item)
    assert item.run_limits == {"budget": {"cost_usd": 15.0}}
    assert len(state["started"]) == 1  # the run started after the budget was on its item
    story = WorkItem(source_type=item.source_type, source_instance=item.source_instance,
                     source_key=f"{item.source_key}-S1", title="story", parent_key=item.source_key,
                     project_id=project_id)
    db.add(story)
    await db.flush()
    assert await inherited_budget(db, story) == {"cost_usd": 15.0}
