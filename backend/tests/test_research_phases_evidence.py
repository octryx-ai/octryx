"""Research evidence: web tool calls, cited URLs, written text, client-side and Codex-hosted searches, retries and workspace knowledge."""

from __future__ import annotations

import pytest

from app.services.workflow_checks.library import TurnEvidence, evaluate_check, validate_checks
from app.services.workflow_checks.urls import added_lines, distinct_urls
from app.services.workflow_runs.octryx.research import RESEARCH_NOTE, with_research
from app.time_utils import utc_now
from tests.research_phases_support import SOURCES, _draft_definition, _list, _patch
from tests.workflow_run_octryx_support import _bound_run, _call

# --- the checks -----------------------------------------------------------------------------------------------------


def _outcome(check: dict, evidence: TurnEvidence) -> tuple[str, str]:
    result = evaluate_check(check, evidence)
    return result.outcome, result.detail


def test_evidence_count_over_the_web_tools_fails_without_searches_and_passes_with_enough():
    from app.services.workflow_checks.library import ToolUse

    check = with_research(_draft_definition()["nodes"][1]["config"], 3)["workflow_contract"]["checks"][0]
    assert _outcome(check, TurnEvidence(tools=[ToolUse("read_workspace_file", True)]))[0] == "failed"
    two = [ToolUse("web_search", True), ToolUse("web_fetch", True), ToolUse("web_fetch", False)]
    assert _outcome(check, TurnEvidence(tools=two)) == ("failed", "2 of 3 evidence calls")  # a failed call is none
    assert _outcome(check, TurnEvidence(tools=[*two, ToolUse("web_search", True)]))[0] == "passed"


def test_urls_cited_counts_distinct_http_urls_in_what_the_phase_wrote():
    text = (f"## Sources\n- {SOURCES[0]}.\n- <{SOURCES[1]}>\n- {SOURCES[1]}/\n- [ICO]({SOURCES[2]})\n"
            "- ftp://files.example.org/x, http://localhost:8000/, https://")
    assert distinct_urls(text) == SOURCES
    check = {"type": "urls_cited", "params": {"min_count": 3}, "blocking": True}
    assert _outcome(check, TurnEvidence(written_files={"SPEC.md": text}))[0] == "passed"
    assert _outcome(check, TurnEvidence(written_files={"SPEC.md": f"{SOURCES[0]} {SOURCES[0]}"})) == (
        "failed", "1 of 3 distinct source URLs cited in SPEC.md")
    # ``path``: only the named file counts; without any written file the answer does.
    scoped = {**check, "params": {"min_count": 3, "path": "**/SPEC.md"}}
    assert _outcome(scoped, TurnEvidence(written_files={"coffee/SPEC.md": text}))[0] == "passed"
    assert _outcome(scoped, TurnEvidence(written_files={"notes.md": text}))[0] == "failed"
    assert _outcome(check, TurnEvidence(answer=text))[0] == "passed"
    assert _outcome(check, TurnEvidence(written_files={"SPEC.md": "no sources"}, answer=text))[0] == "failed"
    for bad in ({"min_count": 0}, {"min_count": "3"}, {"path": ""}, {"min_count": 2, "other": 1}):
        assert [error["code"] for error in validate_checks([{"type": "urls_cited", "params": bad}])] == [
            "invalid_check_params"]


def test_the_written_text_is_the_added_lines_per_file_of_the_change_or_the_platform_write_calls():
    from app.services.workflow_checks.evidence import turn_evidence

    patch = _patch("SPEC.md", ["# Coffee", SOURCES[0]]) + (
        "diff --git a/old.md b/old.md\ndeleted file mode 100644\n--- a/old.md\n+++ /dev/null\n@@ -1 +0,0 @@\n"
        f"-{SOURCES[1]}\n")
    assert added_lines(patch) == {"SPEC.md": f"# Coffee\n{SOURCES[0]}"}
    chat = turn_evidence([{"tool_name": "write_workspace_file", "status": "success", "result": {},
                           "params": {"path": "SPEC.md", "content": " ".join(SOURCES)}},
                          {"tool_name": "edit_workspace_file", "status": "error", "result": {"error": "x"},
                           "params": {"path": "other.md", "new_string": SOURCES[0]}}])
    assert chat.written_files == {"SPEC.md": " ".join(SOURCES)}


def test_claude_codes_own_web_tools_count_when_the_hook_and_the_gateway_recorded_them():
    """The platform's web_search / web_fetch can fail ``transport`` where egress is restricted, so research runs on
    the device: Claude Code's own WebSearch / WebFetch leave from the device and count as the same evidence, under
    the same conditions as a native read."""
    from app.models import ToolCall
    from app.services.agent_gateway.contract import (
        EXECUTION_OUTCOME_SUCCEEDED,
        TOOL_CALL_EXECUTED_KEY,
        TOOL_CALL_SOURCE_HOOK,
    )
    from app.services.workflow_runs.octryx.stop_evidence import phase_evidence

    def native(tool: str, *, hook: bool = True, gateway: bool = True, ok: bool = True) -> ToolCall:
        parameters = {"source": "model_gateway", **({"block_index": 0} if gateway else {})}
        if hook:
            parameters[TOOL_CALL_EXECUTED_KEY] = {"source": TOOL_CALL_SOURCE_HOOK,
                                                  "outcome": EXECUTION_OUTCOME_SUCCEEDED if ok else "failed"}
        return ToolCall(session_id="s", tool_name=tool, parameters=parameters, status="success",
                        created_at=utc_now())

    rows = [native("WebSearch"), native("WebFetch"), native("WebFetch"), native("WebSearch", hook=False),
            native("WebFetch", gateway=False), native("WebSearch", ok=False)]
    evidence = phase_evidence(rows, since=None, test_prefixes=())
    assert [(use.name, use.succeeded) for use in evidence.tools] == [
        ("web_search", True), ("web_fetch", True), ("web_fetch", True),
        ("web_search", False), ("web_fetch", False), ("web_search", False)]
    check = with_research(_draft_definition()["nodes"][1]["config"], 3)["workflow_contract"]["checks"][0]
    assert _outcome(check, evidence)[0] == "passed"
    assert "WebSearch" in RESEARCH_NOTE and "web_search" in RESEARCH_NOTE


@pytest.mark.asyncio
async def test_a_failing_connection_to_the_search_provider_or_a_page_is_tried_again(monkeypatch):
    """Intermittent ``transport`` / "All connection attempts failed"."""
    import httpx

    from app.services.web_search import providers
    from app.tools.runtime_impl import _runtime_bash_web

    slept: list[float] = []

    async def no_wait(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(providers, "_sleep", no_wait)
    answers = iter([httpx.ConnectError("All connection attempts failed"), httpx.Response(503),
                    httpx.Response(200, json={"results": []})])

    def handler(request: httpx.Request) -> httpx.Response:
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    assert await providers._post(client, "https://search.test/q", headers={}, payload={}) == {"results": []}
    assert slept == [1.0, 3.0]
    slept.clear()
    answers = iter([httpx.ConnectError("down")] * 3)
    with pytest.raises(providers.SearchProviderError, match="transport"):
        await providers._post(client, "https://search.test/q", headers={}, payload={})
    answers = iter([httpx.Response(401)])
    with pytest.raises(providers.SearchProviderError, match="unauthorized"):  # a refusal is not retried
        await providers._post(client, "https://search.test/q", headers={}, payload={})

    pages = iter([httpx.ConnectError("All connection attempts failed"),
                  httpx.Response(200, text="<html><title>Roast</title>ok</html>",
                                 headers={"content-type": "text/html"})])

    def page(request: httpx.Request) -> httpx.Response:
        answer = next(pages)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(_runtime_bash_web, "public_web_client",
                        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(page), **kwargs))
    monkeypatch.setattr(_runtime_bash_web, "FETCH_RETRY_DELAYS", (0.0, 0.0))

    async def allowed(*_args, **_kwargs):
        return None

    from app.services.web_search import fetch_policy

    monkeypatch.setattr(fetch_policy, "web_fetch_refusal", allowed)
    from app.tools.context import ToolContext

    fetched = await _runtime_bash_web.WebFetchTool().execute(
        {"url": "https://wiki.example.org/wiki/Coffee_roasting"},
        ToolContext(user_id="u", project_ids=[], roles=[], session_id="s", project_config={}))
    assert "error" not in fetched and fetched["url"].endswith("Coffee_roasting")


def test_a_web_call_that_found_nothing_is_no_evidence():
    """Every platform web_search answers ``unavailable`` / ``transport``; the check must not count the calls (the MCP
    call itself succeeds) while the spec cites URLs from the model's memory."""
    from app.services.observability.knowledge_metrics import web_result_ok

    assert web_result_ok("web_search", {"excerpt": '{"state": "ok", "results": [{"url": "u"}], "count": 1}'})
    assert not web_result_ok("web_search", {"excerpt": '{"state": "unavailable", "reason": "transport"}'})
    assert not web_result_ok("web_search", {"excerpt": '{"state":"ok","results":[],"count":0}'})  # no hits
    assert not web_result_ok("web_search", {})
    assert web_result_ok("web_fetch", {"excerpt": '{"url": "https://coffee.example", "title": "SCA", "content": "x"}'})
    assert not web_result_ok("web_fetch", {"excerpt": '{"error": "Fetch failed: All connection attempts failed"}'})
    assert not web_result_ok("web_fetch", {"excerpt": '{"state": "denied", "reason": "source_blocked"}'})
    assert web_result_ok("read_workspace_file", {})  # only the web tools are read this way


def test_codex_hosted_searches_from_the_reported_answer_count_as_web_search():
    """Research runs on the device. Codex's hosted search (a research phase on the seat) is recorded
    from the answer the platform admitted and the device reported; a completed one is web_search evidence."""
    import json as _json

    from app.services.model_gateway.inbound.anthropic_stream import Observation
    from app.services.model_gateway.inbound.codex_seat_observer import CodexSeatObserver, observe_responses_body
    from app.services.model_gateway.inbound.seat_transcript import hosted_search_row
    from app.services.workflow_runs.octryx.stop_evidence import phase_evidence

    items = [{"type": "web_search_call", "id": "ws_1", "status": "completed",
              "action": {"type": "search", "query": "specialty coffee roast rest days"}},
             {"type": "web_search_call", "id": "ws_2", "status": "failed", "action": {"type": "search", "query": "x"}},
             {"type": "message", "content": [{"type": "output_text", "text": "done"}]}]
    observation = Observation()
    observe_responses_body(observation, {"output": items, "usage": {}})
    assert [(item["id"], item["status"]) for item in observation.hosted_searches] == [("ws_1", "completed"),
                                                                                     ("ws_2", "failed")]
    assert observation.tool_uses == [] and observation.text == "done"  # no tool call of the conversation
    streamed = Observation()
    observer = CodexSeatObserver(streamed)
    event = {"type": "response.output_item.done", "item": items[0]}
    observer.feed(f"event: response.output_item.done\ndata: {_json.dumps(event)}\n\n".encode())
    observer.finish()
    assert [item["target"] for item in streamed.hosted_searches] == ["specialty coffee roast rest days"]

    rows = [hosted_search_row("s", search) for search in observation.hosted_searches]
    for row in rows:
        row.created_at = utc_now()
    assert [(use.name, use.succeeded) for use in phase_evidence(rows, since=None, test_prefixes=()).tools] == [
        ("web_search", True), ("web_search", False)]


@pytest.mark.asyncio
async def test_the_workspaces_knowledge_counts_as_research_and_its_citations_as_sources(db, monkeypatch):
    """Knowledge first, then web search: a knowledge search with hits is research evidence (one
    without hits is not), a cite_as link to the platform counts as a cited source also on a host without a dot, and
    every phase that may search the knowledge is told to ask it first."""
    from types import SimpleNamespace

    from app.config import get_settings
    from app.services.workflow_runs.octryx.hooks import session_contract
    from app.services.workflow_runs.octryx.stop_evidence import phase_evidence
    from app.services.workflow_runs.run_texts import run_text

    def search(count: int):
        row = _call(SimpleNamespace(id="s"), "mcp__octryx-knowledge__knowledge_search", at=utc_now())
        row.result = {"is_error": False, "excerpt": f'{{"state": "ok", "result_count": {count}, "evidence": []}}'}
        return row

    uses = phase_evidence([search(3), search(0)], since=None, test_prefixes=()).tools
    assert [use.name for use in uses] == ["knowledge_search", "knowledge_hit", "knowledge_search"]
    monkeypatch.setattr(get_settings(), "platform_public_origin", "http://localhost:24260")
    cited = "- Brew ratio (Workspace knowledge): http://localhost:24260/knowledge/x\n- http://localhost:9999/y"
    assert distinct_urls(cited) == ["http://localhost:24260/knowledge/x"]

    run, gateway, _key, workspace_id = await _bound_run(db, _draft_definition())
    assert "knowledge_first" not in (await session_contract(db, gateway))["phase"]  # no knowledge_search offered
    await _list(db, workspace_id, [f"{run.workflow_key}.draft"])  # researching: knowledge_search is offered
    assert (await session_contract(db, gateway))["phase"]["knowledge_first"] == run_text("contract.knowledge_first")
