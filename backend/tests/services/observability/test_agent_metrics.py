"""Agent metrics on /metrics (services/observability/agent_metrics.py): what is committed counts, nothing else."""

from __future__ import annotations

import asyncio
import re
import uuid
from decimal import Decimal

import pytest

from app.agent.providers.base import BaseLLMProvider
from app.models import Approval, ToolCall, UsageEvent, WorkflowRun
from app.services.approval.resolution_service import decide_pending_approval
from app.services.observability import agent_metrics, metric_types
from app.time_utils import utc_now
from tests.observability_support import admin_user, call_as, session_for, workspace

#: These tests call provider drivers directly: they run as the platform (``tests/support/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")


@pytest.fixture(autouse=True)
def _empty_metrics():
    agent_metrics.reset()
    yield
    agent_metrics.reset()


def _value(text: str, line_start: str) -> float:
    found = [line for line in text.splitlines() if line.startswith(line_start + " ")]
    assert len(found) == 1, (line_start, [line for line in text.splitlines() if line.startswith(line_start[:30])])
    return float(found[0].rsplit(" ", 1)[1])


@pytest.mark.asyncio
async def test_committed_agent_work_is_counted_and_rolled_back_work_is_not(client, db):
    admin = await admin_user(db)
    project = await workspace(db, "Payments")
    session = await session_for(db, admin, project=project)
    db.add(UsageEvent(id=str(uuid.uuid4()), session_id=session.id, user_id=admin.id, provider="bedrock",
                      model="claude-x", tokens_in=1200, tokens_out=300, cache_read_tokens=50, cost=Decimal("0.0125")))
    db.add(ToolCall(session_id=session.id, tool_name="read_file", status="success", duration_ms=250))
    run = WorkflowRun(project_id=project.id, workflow_kind="phased", workflow_key="ticket-delivery", title="t",
                      requested_by=admin.id)
    db.add(run)
    await db.commit()
    session_id, admin_id, project_id, run_id = session.id, admin.id, project.id, run.id

    db.add(ToolCall(session_id=session_id, tool_name="read_file", status="error", duration_ms=10))
    await db.flush()
    await db.rollback()

    run = await db.get(WorkflowRun, run_id)
    run.status, run.completed_at = "completed", utc_now()
    approval = Approval(session_id=session_id, requested_by=admin_id, action="tool:shell", status="pending")
    db.add(approval)
    await db.commit()
    await decide_pending_approval(db, approval_id=approval.id, resolved_by=admin_id, status="rejected")
    await db.commit()

    text = (await call_as(client, "GET", "/metrics", await admin_user(db))).text
    llm = 'provider="bedrock",model="claude-x",route="governed"'
    who = 'engine="governed",role="none",workspace="Payments"'
    assert _value(text, f'octryx_llm_tokens_total{{{llm},type="input",{who}}}') == 1200
    assert _value(text, f'octryx_llm_tokens_total{{{llm},type="cache_read",{who}}}') == 50
    assert _value(text, f"octryx_llm_cost_usd_total{{{llm}}}") == 0.0125
    assert _value(text, 'octryx_tool_calls_total{tool="read_file",status="success"}') == 1
    assert 'octryx_tool_calls_total{tool="read_file",status="error"}' not in text
    assert _value(text, 'octryx_tool_call_duration_seconds_bucket{tool="read_file",le="0.25"}') == 1
    assert _value(text, 'octryx_agent_sessions_started_total{agent_type="chat",origin="chat",kind="main"}') == 1
    # A Workspace is shown by its name, never by its id.
    assert _value(text, 'octryx_workflow_runs_started_total{workflow="ticket-delivery",workspace="Payments"}') == 1
    assert _value(text, 'octryx_workflow_runs_finished_total{workflow="ticket-delivery",workspace="Payments",'
                        'status="completed"}') == 1
    assert _value(text, 'octryx_workflow_run_duration_seconds_count{workflow="ticket-delivery",status="completed"}') == 1
    assert project_id not in text
    assert _value(text, 'octryx_approvals_requested_total{source="session"}') == 1
    assert _value(text, 'octryx_approvals_decided_total{status="rejected"}') == 1
    # The live gauges come from memory: the approval is decided, its newest state says so.
    assert f'octryx_approval_state{{approval="{str(approval.id)[:12]}",source="session",status="rejected"}}' in text
    for name in ("octryx_llm_tokens_total", "octryx_workflow_run_duration_seconds", "octryx_agent_session_state"):
        assert f"# TYPE {name} " in text


class _Fake(BaseLLMProvider):
    name = "fake"

    def __init__(self, inner: BaseLLMProvider | None = None, fail: BaseException | None = None) -> None:
        self.inner, self.fail = inner, fail

    async def chat(self, messages, model, tools=None, temperature=0, max_tokens=4096, reasoning_effort=None):
        if self.fail is not None:
            raise self.fail
        if self.inner is not None:
            return await self.inner.chat(messages, model)
        return {"content": "ok", "usage": {}, "model": model}

    async def list_models(self):
        return []

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_every_provider_counts_its_requests_once_with_outcome_and_duration():
    await _Fake().chat([], "m1")
    await _Fake(inner=_Fake()).chat([], model="m1")
    with pytest.raises(TimeoutError):
        await _Fake(fail=TimeoutError()).chat([], "m1")
    with pytest.raises(RuntimeError):
        await _Fake(fail=RuntimeError("down")).chat([], "m1")

    text = "\n".join(agent_metrics.render())
    fake = 'provider="fake",model="m1",route="governed"'
    assert _value(text, f'octryx_llm_requests_total{{{fake},outcome="ok"}}') == 2
    assert _value(text, f'octryx_llm_requests_total{{{fake},outcome="timeout"}}') == 1
    assert _value(text, f'octryx_llm_requests_total{{{fake},outcome="error"}}') == 1
    assert _value(text, f'octryx_llm_request_duration_seconds_count{{{fake}}}') == 4


def test_label_values_stay_bounded_and_escaped():
    agent_metrics.TURNS.inc(agent='say "hi"\n', outcome="ok")
    for index in range(metric_types.MAX_SERIES + 20):
        agent_metrics.TURNS.inc(agent=f"agent {index}", outcome="ok")

    lines = [line for line in agent_metrics.TURNS.render() if not line.startswith("#")]
    assert len(lines) == metric_types.MAX_SERIES + 1
    assert float(next(line for line in lines if 'agent="other"' in line).rsplit(" ", 1)[1]) == 21
    assert any('agent="say \\"hi\\"\\n"' in line for line in lines)
    assert all(re.fullmatch(r'octryx_agent_turns_total\{agent="([^"\\\n]|\\.)*",outcome="[^"]*"\} \d+', line)
               for line in lines)


@pytest.mark.asyncio
async def test_the_worker_serves_its_own_counters_only_to_the_scraper(monkeypatch):
    from app.config import get_settings
    from app.worker_main import WorkerHealthServer

    monkeypatch.setattr(get_settings(), "metrics_scrape_token", "scrape-secret-for-tests")
    agent_metrics.TOOL_CALLS.inc(tool="run_tests", status="success")
    server = WorkerHealthServer(None, host="127.0.0.1", port=0)
    await server.start()

    async def get(token: str | None) -> tuple[str, str]:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
        auth = f"Authorization: Bearer {token}\r\n" if token else ""
        writer.write(f"GET /metrics HTTP/1.1\r\nHost: w\r\n{auth}\r\n".encode())
        await writer.drain()
        answer = (await reader.read()).decode()
        writer.close()
        return answer.split("\r\n", 1)[0], answer.split("\r\n\r\n", 1)[1]

    try:
        assert (await get(None))[0] == "HTTP/1.1 401 Unauthorized"
        assert (await get("wrong"))[0] == "HTTP/1.1 401 Unauthorized"
        status, body = await get("scrape-secret-for-tests")
    finally:
        await server.stop()
    assert status == "HTTP/1.1 200 OK"
    assert 'octryx_tool_calls_total{tool="run_tests",status="success"} 1' in body
