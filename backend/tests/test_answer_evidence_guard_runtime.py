"""At the runtime boundary web answers are marked or recorded, and web search and fetch results carry their source URL."""

from __future__ import annotations

import ipaddress
import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import run_agent
from app.models import Message, Project, Session, TurnTrace, User
from app.services.answer_evidence.evidence import collect_turn_evidence
from app.services.answer_evidence.record import read_answer_evidence
from app.services.answer_evidence.texts import REMINDER_MARKER
from app.services.web_search.providers import SearchHit
from app.services.web_search.service import SearchOutcome
from app.tools.runtime_impl._runtime_web_search_tools import _answer
from tests.answer_evidence_guard_support import CITED_PETCLINIC, PETCLINIC_OWNER, UNCITED_PETCLINIC
from tests.egress_support import answer_public_web
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN

# --- end to end over run_agent ---------------------------------------------------------------------


async def _chat_session(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="chat", status="running",
        metadata_=dict(UNDECLARED_READ_ONLY_RUN),
    )
    db.add(session)
    await db.commit()
    return admin, project, session


def _model(monkeypatch, replies: list[dict]) -> list[list[dict]]:
    seen: list[list[dict]] = []

    async def fake_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "bedrock", "model": "anthropic.claude-sonnet-4-5"}]

    async def fake_chat(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None, **_kwargs):
        seen.append(list(messages))
        reply = replies.pop(0)
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        return {"tool_calls": None, "model": "anthropic.claude-sonnet-4-5", **reply, "usage": usage}, runtimes[0]

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat)
    return seen


def _fetch_call() -> dict:
    return {
        "content": "",
        "tool_calls": [{"id": "call-fetch", "function": {"name": "web_fetch", "arguments": f'{{"url": "{PETCLINIC_OWNER}"}}'}}],
    }


def _serve_owner_java(monkeypatch) -> None:
    async def resolve(hostname: str, port: int | None):
        return {ipaddress.ip_address("185.199.108.133")}

    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, text='@OrderBy("name")\nprivate List<Pet> pets;', request=request
        )

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", resolve)
    answer_public_web(monkeypatch, handler)


async def _run(db, admin, project, session, message: str) -> list[str]:
    contents: list[str] = []
    async for event in run_agent(
        session_id=session.id, user_message=message, user_id=admin.id, project_id=project.id, agent_type="chat", db=db
    ):
        if getattr(event, "role", "") == "assistant" and getattr(event, "content", ""):
            contents.append(str(event.content))
    return contents


async def _records(db, session_id: str) -> list[dict]:
    traces = (
        await db.execute(select(TurnTrace).where(TurnTrace.session_id == session_id).order_by(TurnTrace.created_at))
    ).scalars().all()
    return [record for trace in traces if (record := read_answer_evidence(trace.context_snapshot_json))]


@pytest.mark.asyncio
async def test_a_web_fetch_answer_without_links_is_delivered_marked_at_the_runtime_boundary(db, monkeypatch) -> None:
    admin, project, session = await _chat_session(db)
    _serve_owner_java(monkeypatch)
    seen = _model(monkeypatch, [_fetch_call(), {"content": UNCITED_PETCLINIC}, {"content": UNCITED_PETCLINIC}])

    contents = await _run(db, admin, project, session, "How does Owner order its pets in spring-petclinic?")

    assert len(seen) == 3, "fetch, uncited answer, reminder, uncited answer again"
    fetched = next(m for m in seen[1] if m.get("role") == "tool")
    assert PETCLINIC_OWNER in str(fetched.get("content")) and "source_url" in str(fetched.get("content"))
    assert any(str(m.get("content") or "").startswith(REMINDER_MARKER) for m in seen[2])
    # Delivered, never withheld; the note names the source the answer did not link.
    assert "withheld" not in contents[-1] and "visit_date" in contents[-1]
    assert "No source linked" in contents[-1] and PETCLINIC_OWNER in contents[-1]
    rows = (await db.execute(select(Message).where(Message.session_id == session.id, Message.role == "assistant"))).scalars().all()
    assert any("No source linked" in str(row.content) for row in rows), "the stored answer is the marked one"
    assert [record["evidence_guard"] for record in await _records(db, session.id)][-2:] == ["reminded", "marked"]


@pytest.mark.asyncio
async def test_a_cited_web_fetch_answer_is_delivered_and_recorded_as_passed(db, monkeypatch) -> None:
    admin, project, session = await _chat_session(db)
    _serve_owner_java(monkeypatch)
    _model(monkeypatch, [_fetch_call(), {"content": CITED_PETCLINIC}])

    contents = await _run(db, admin, project, session, "How does Owner order its pets in spring-petclinic?")

    assert contents[-1] == CITED_PETCLINIC
    assert (await _records(db, session.id))[-1]["evidence_guard"] == "passed"


@pytest.mark.asyncio
async def test_a_greeting_turn_is_unchanged_and_marked_unsourced(db, monkeypatch) -> None:
    admin, project, session = await _chat_session(db)
    seen = _model(monkeypatch, [{"content": "Hello! How can I help you today?"}])

    contents = await _run(db, admin, project, session, "Hi there")

    assert len(seen) == 1 and contents[-1] == "Hello! How can I help you today?"
    assert (await _records(db, session.id))[-1]["evidence_guard"] == "unsourced"


# --- web evidence carries its URL -------------------------------------------------------------------


def test_web_search_results_carry_source_url_and_cite_as() -> None:
    outcome = SearchOutcome(state="ok", reason="ok", provider="tavily", hits=[SearchHit("Owner.java", PETCLINIC_OWNER, "x")])
    hit = _answer(outcome, query="petclinic owner", mode="open")["results"][0]
    assert (hit["source_title"], hit["source_url"], hit["cite_as"]) == (
        "Owner.java",
        PETCLINIC_OWNER,
        f"[Owner.java]({PETCLINIC_OWNER})",
    )
    assert collect_turn_evidence([{"tool_name": "web_search", "result": {"results": [hit]}}]).evidence_bearing


@pytest.mark.asyncio
async def test_web_fetch_results_carry_source_url_and_the_page_title(monkeypatch) -> None:
    from app.tools.runtime_impl._runtime_bash_web import WebFetchTool

    async def resolve(hostname: str, port: int | None):
        return {ipaddress.ip_address("93.184.216.34")}

    def handler(request):
        page = "<html><head><title>Owner &amp; Pets</title></head><body>x</body></html>"
        return httpx.Response(200, headers={"content-type": "text/html"}, text=page, request=request)

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", resolve)
    answer_public_web(monkeypatch, handler)

    result = await WebFetchTool().execute({"url": "https://example.com/owner"}, SimpleNamespace())

    assert result["source_url"] == "https://example.com/owner"
    assert result["cite_as"] == "[Owner & Pets](https://example.com/owner)"
