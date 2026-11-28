"""A refused call names the kind of secret on the run's timeline, never its value;
the kinds come from the request's one scan, so the timeline note never scans again."""

from __future__ import annotations

import pytest

from app.services.content_detection import examination
from app.services.content_detection.examination import RequestBudget
from app.services.content_security.enforcement_inbound import InboundPlan
from app.services.content_security.format_request_body import examine_request_body
from app.services.model_gateway.inbound.refusals import REASON_SECRET_DETECTED, refusal
from app.services.model_gateway.inbound.secret_refusal_note import EVENT, note_secret_refusal
from app.services.policy_engine.runtime import PolicyRuntime, set_policy_runtime
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

TOKEN = "ghp_" + "a1B2" * 9  # a made-up shape


def _body(text: str) -> dict:
    return {"model": "m", "messages": [
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                      "content": [{"type": "text", "text": text}]}]},
        {"role": "assistant", "content": "ok"}, {"role": "user", "content": "next"}]}


def _found(text: str) -> tuple[dict[str, str], ...]:
    set_policy_runtime(PolicyRuntime())
    return examine_request_body(_body(text), "ws-1", RequestBudget()).secret_kinds()


def test_the_kind_never_the_value():
    found = _found(f"cloned with {TOKEN} today")
    assert found == ({"kind": "vendor_token", "source": "request"},)
    assert TOKEN not in str(found)
    assert _found("password = settings.db_password") == ()


def test_the_whole_body_is_scanned_once(monkeypatch):
    calls: list[int] = []
    real = examination.scan

    def counted(segments, *args, **kwargs):
        calls.append(len(segments))
        return real(segments, *args, **kwargs)

    monkeypatch.setattr(examination, "scan", counted)
    assert _found(f"cloned with {TOKEN} today")
    assert calls == [1], "one scan of the whole body answers for its tool result, the newest turn and its own text"


def _plan(reason: str) -> InboundPlan:
    return InboundPlan(refusal=refusal("denied", reason, http_status=400),
                       found=({"kind": "vendor_token", "source": "tool_result"},))


@pytest.mark.asyncio
async def test_the_run_records_it_only_for_the_secret_scan_without_scanning_again(db, monkeypatch):
    from sqlalchemy import select

    from app.models import WorkflowRunEvent
    from tests.hands_on_support import _at_hands_on

    run, session, _offered, _factory = await _at_hands_on(db, monkeypatch)

    async def active(_db, _session_id):
        return run

    def no_scan(*_args, **_kwargs):
        raise AssertionError("the note never scans the request")

    monkeypatch.setattr("app.services.workflow_runs.records.active_run_for_session", active)
    monkeypatch.setattr(examination, "scan", no_scan)
    await note_secret_refusal(db, session.id, _plan("content_policy_denied"))
    await note_secret_refusal(db, session.id, _plan(REASON_SECRET_DETECTED))
    events = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == EVENT))).scalars().all()
    assert [event.detail["found"] for event in events] == [[{"kind": "vendor_token", "source": "tool_result"}]]
    assert TOKEN not in str(events[0].detail)
