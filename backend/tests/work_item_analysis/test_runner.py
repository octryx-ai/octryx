"""analyze_work_item — governed, cited, idempotent per item version, explicit refusals."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import AgentBoardMessage, AuditLog, Session, UsageEvent, WorkItem, WorkItemAnalysis
from app.services.work_item_analysis import governed_run, runner
from app.services.work_item_analysis.prompt import TEMPLATE_KEY
from app.services.work_item_analysis.runner import analyze_work_item
from tests.work_item_analysis.support import (
    MANUAL_PAGE,
    Scripted,
    analysis,
    final,
    run_options,
    seed_env,
    tool_call,
)

SEARCH = tool_call("knowledge_search", {"query": "TLS error import"})


async def _notes(db, item_id: str) -> list[dict]:
    item = await db.get(WorkItem, item_id)
    await db.refresh(item)
    return [note for note in (item.source_fields_json or {}).get("platform_notes") or []]


@pytest.mark.asyncio
async def test_a_cited_analysis_is_stored_as_an_agent_note_with_a_board_info(db, monkeypatch):
    env = await seed_env(db, monkeypatch)
    scripted = Scripted([SEARCH, final(analysis())])
    answer = await analyze_work_item(db, item=env.item, user=env.user, **run_options(scripted))

    assert (answer["status"], answer["error_code"], answer["reused"]) == ("succeeded", None, False)
    assert answer["analysis"]["evidence"][0]["verified"] is True
    assert answer["content_is_data"].startswith("An analysis is data")
    [note] = await _notes(db, env.item.id)
    assert (note["kind"], note["author_type"], note["analysis_id"]) == ("analysis", "agent", answer["id"])
    assert MANUAL_PAGE in note["note"] and "Open questions for the reporter" in note["note"]
    assert note["summary"] == analysis()["summary"]  # what the ServiceNow work note sends
    message = await db.get(AgentBoardMessage, answer["board_message_id"])
    assert (message.kind, message.work_item_id, message.author_type) == ("info", env.item.id, "agent")
    assert answer["id"] in message.body
    row = await db.get(WorkItemAnalysis, answer["id"])
    session = await db.get(Session, row.session_id)
    assert (session.agent_type, session.status) == ("work_item_analysis", "completed")
    assert session.metadata_["execution_profile"]["capability"] == {
        "class": "read_only", "source": "work_item_analysis", "enforced": True}
    assert row.template == TEMPLATE_KEY and row.active_key and row.tools_json["template_digest"]
    assert set(answer["tools"]["offered"]) >= {"knowledge_search", "knowledge_read", "work_item_context"}
    assert (await db.execute(select(UsageEvent).where(UsageEvent.session_id == row.session_id))).scalars().all()
    actions = [a.action for a in (await db.execute(select(AuditLog).where(
        AuditLog.resource_id == env.item.id))).scalars()]
    assert {"work_item_analysis.started", "work_item_analysis.finished"} <= set(actions)
    # The item's state is never changed by an analysis.
    assert (await db.get(WorkItem, env.item.id)).work_state == "intake"
    # The model saw only the fixed tool surface, and the item text arrived as quoted data.
    offered = {tool["function"]["name"] for tool in scripted.seen[0]["tools"]}
    assert offered == set(answer["tools"]["offered"])
    assert "never instructions" in scripted.seen[0]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_the_same_item_version_is_never_analysed_twice(db, monkeypatch):
    env = await seed_env(db, monkeypatch)
    first = await analyze_work_item(db, item=env.item, user=env.user, **run_options(Scripted([SEARCH, final(analysis())])))
    again = await analyze_work_item(db, item=env.item, user=env.user, **run_options(Scripted([])))
    assert (again["id"], again["reused"], again["status"]) == (first["id"], True, "succeeded")
    env.item.description = "Since Monday the import stops with a TLS error. Now also on staging."
    await db.commit()
    changed = await analyze_work_item(db, item=env.item, user=env.user,
                                      **run_options(Scripted([SEARCH, final(analysis())])))
    assert changed["id"] != first["id"] and changed["reused"] is False


@pytest.mark.asyncio
async def test_a_running_analysis_holds_the_slot(db, monkeypatch):
    env = await seed_env(db, monkeypatch)
    from app.services.work_item_analysis.prompt import item_version

    key = f"{env.item.id}:{item_version(env.item)}:{TEMPLATE_KEY}"
    db.add(WorkItemAnalysis(project_id=env.workspace_id, work_item_id=env.item.id, item_version="v", template="t",
                            active_key=key, mode="manual", status="running", requested_by=env.user.id,
                            cost_usd=Decimal("0"), tokens_in=0, tokens_out=0))
    await db.commit()
    answer = await analyze_work_item(db, item=env.item, user=env.user, **run_options(Scripted([])))
    assert (answer["status"], answer["reused"]) == ("running", True)


@pytest.mark.asyncio
@pytest.mark.parametrize(("reply", "code"), [
    ("I think it is the certificate.", "analysis_not_json"),
    ({"summary": "x"}, "analysis_invalid"),
])
async def test_an_answer_that_is_not_the_contract_fails_and_frees_the_slot(db, monkeypatch, reply, code):
    env = await seed_env(db, monkeypatch)
    failed = await analyze_work_item(db, item=env.item, user=env.user, **run_options(Scripted([final(reply)])))
    assert (failed["status"], failed["error_code"]) == ("failed", code)
    assert (await db.get(WorkItemAnalysis, failed["id"])).active_key is None
    assert await _notes(db, env.item.id) == []
    retried = await analyze_work_item(db, item=env.item, user=env.user, **run_options(Scripted([SEARCH, final(analysis())])))
    assert retried["status"] == "succeeded" and retried["id"] != failed["id"]


@pytest.mark.asyncio
async def test_a_citation_no_tool_returned_is_refused_or_flagged(db, monkeypatch):
    env = await seed_env(db, monkeypatch)
    invented = {"claim": "Invented.", "source": {"kind": "manual", "title": "Manual", "locator": "page 999",
                                                 "url": None}}
    uncited = await analyze_work_item(db, item=env.item, user=env.user, **run_options(
        Scripted([SEARCH, final(analysis(evidence=[invented]))])))
    assert (uncited["status"], uncited["error_code"]) == ("failed", "analysis_uncited")
    real = analysis()["evidence"][0]
    mixed = await analyze_work_item(db, item=env.item, user=env.user, **run_options(
        Scripted([SEARCH, final(analysis(evidence=[real, invented]))])))
    assert mixed["status"] == "succeeded"
    assert [entry["verified"] for entry in mixed["analysis"]["evidence"]] == [True, False]
    [note] = await _notes(db, env.item.id)
    assert "page 999" in note["note"] and "[not confirmed by a tool result]" in note["note"]


@pytest.mark.asyncio
async def test_work_item_context_is_pinned_to_the_analysed_item(db, monkeypatch):
    env = await seed_env(db, monkeypatch)
    peek = tool_call("work_item_context", {"work_item": "OTHER-1", "include_session_digests": True})
    await analyze_work_item(db, item=env.item, user=env.user, **run_options(Scripted([peek, final(analysis())])))
    assert env.context_calls == [{"work_item": env.item.id, "include_session_digests": False}]


@pytest.mark.asyncio
async def test_without_a_model_policy_nothing_is_sent_to_a_model(db, monkeypatch):
    env = await seed_env(db, monkeypatch, settings={})
    scripted = Scripted([SEARCH, final(analysis())])
    answer = await analyze_work_item(db, item=env.item, user=env.user, **run_options(scripted))
    assert (answer["status"], answer["error_code"]) == ("needs_configuration", "model_policy_unresolved")
    assert scripted.seen == [] and await _notes(db, env.item.id) == []


@pytest.mark.asyncio
async def test_a_core_tool_the_workspace_puts_behind_approval_denies_the_run(db, monkeypatch):
    env = await seed_env(db, monkeypatch, project_config={"approval_policy": {"require_for_tools": ["knowledge_search"]}})
    scripted = Scripted([SEARCH, final(analysis())])
    answer = await analyze_work_item(db, item=env.item, user=env.user, **run_options(scripted))
    assert (answer["status"], answer["error_code"]) == ("denied", "tool_requires_approval") and scripted.seen == []


@pytest.mark.asyncio
async def test_the_cost_cap_stops_further_requests(db, monkeypatch):
    env = await seed_env(db, monkeypatch, settings={"model_policy": "analysis-policy@1", "cost_cap_usd": 1})

    async def priced(*_args, **_kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(cost=Decimal("0.6"))

    monkeypatch.setattr("app.services.governed_agent_run.model_call.compute_usage_event_cost_attribution", priced)
    scripted = Scripted([SEARCH, tool_call("knowledge_read", {"query": "x"}, "call-2"), final(analysis())])
    answer = await analyze_work_item(db, item=env.item, user=env.user, **run_options(scripted))
    assert (answer["status"], answer["error_code"]) == ("failed", "cost_cap_reached")
    assert len(scripted.seen) == 2 and answer["cost_usd"] == pytest.approx(1.2)


@pytest.mark.asyncio
async def test_a_secret_in_the_analysis_is_never_stored(db, monkeypatch):
    env = await seed_env(db, monkeypatch)
    leaked = analysis(summary="Use the key AKIA" + "IOSFODNN7EXAMPLE to retry.")
    answer = await analyze_work_item(db, item=env.item, user=env.user, **run_options(
        Scripted([SEARCH, final(leaked)])))
    assert (answer["status"], answer["error_code"], answer["analysis"]) == ("failed", "secret_detected", None)
    assert await _notes(db, env.item.id) == []


@pytest.mark.asyncio
async def test_a_crash_after_the_run_frees_the_slot_and_keeps_nothing_half_written(db, monkeypatch):
    env = await seed_env(db, monkeypatch)

    async def broken(*_args, **_kwargs):
        raise RuntimeError("board down")

    monkeypatch.setattr(runner, "post_analysis_info", broken)
    answer = await analyze_work_item(db, item=env.item, user=env.user, **run_options(
        Scripted([SEARCH, final(analysis())])))
    assert (answer["status"], answer["error_code"]) == ("failed", "analysis_runtime_error")
    row = await db.get(WorkItemAnalysis, answer["id"])
    assert row.active_key is None and row.finished_at is not None
    assert await _notes(db, env.item.id) == []


@pytest.mark.asyncio
async def test_automatic_runs_skip_closed_items_and_wait_24_hours(db, monkeypatch):
    env = await seed_env(db, monkeypatch)
    first = await analyze_work_item(db, item=env.item, user=env.user, mode="auto",
                                    **run_options(Scripted([SEARCH, final(analysis())])))
    assert first["status"] == "succeeded"
    env.item.title = "Nightly import fails (new detail)"
    await db.commit()
    limited = await analyze_work_item(db, item=env.item, user=env.user, mode="auto", **run_options(Scripted([])))
    assert (limited["status"], limited["error_code"]) == ("skipped", "auto_rate_limited")
    env.item.work_state = "done"
    await db.commit()
    closed = await analyze_work_item(db, item=env.item, user=env.user, mode="auto", **run_options(Scripted([])))
    assert closed["error_code"] == "item_closed"
    manual = await analyze_work_item(db, item=env.item, user=env.user,
                                     **run_options(Scripted([SEARCH, final(analysis())])))
    assert manual["status"] == "succeeded"  # a person may still ask for one


def test_the_runner_dispatches_under_its_own_registered_owner():
    from app.services.model_gateway.dispatch_owners import DISPATCH_OWNERS

    owner = DISPATCH_OWNERS[governed_run.DISPATCH_OWNER]
    assert owner.module == "app/services/work_item_analysis/governed_run.py" and owner.requires_admission


@pytest.mark.asyncio
async def test_the_servicenow_work_note_sends_exactly_the_analysis_summary(db, monkeypatch):
    from app.services.secure_work.servicenow.worknote import worknote_text

    env = await seed_env(db, monkeypatch, source_type="servicenow")
    await analyze_work_item(db, item=env.item, user=env.user, **run_options(Scripted([SEARCH, final(analysis())])))
    [note] = await _notes(db, env.item.id)
    assert worknote_text(note) == analysis()["summary"]  # never the evidence or the header line
