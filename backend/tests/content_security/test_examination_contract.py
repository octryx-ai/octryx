"""The examination contract itself, and one property per consumer under every cause of an unfinished scan."""

from __future__ import annotations

import json
import types

import httpx
import pytest

from app.services.content_detection import scanner
from app.services.content_detection.builtin import CandidateLimitError
from app.services.content_detection.examination import (
    DISPOSITION_ALLOW,
    DISPOSITION_WITHHOLD,
    DOMAIN_FIELDS,
    DOMAIN_STRUCTURED,
    DOMAIN_TEXT,
    CleanCache,
    CleanEntry,
    Examination,
    IncompleteExaminationError,
    RequestBudget,
    compose,
    examine,
    examine_text,
)
from app.services.content_detection.masking import WITHHELD_TEXT
from app.services.content_detection.scanner import DetectorSet, ScanReport, Segment
from app.services.policy_engine.runtime import PolicyRuntime, set_policy_runtime
from tests.content_security.examination_boundary_cases import BOUNDARY_CASES
from tests.content_security.examination_edge_cases import EDGE_CASES
from tests.content_security.examination_final_cases import FINAL_CASES
from tests.content_security.launcher_chain_support import (
    launcher_disposition_case,
    launcher_hook_case,
    launcher_route_case,
)
from tests.model_gateway.codex_seat_support import chatgpt  # noqa: F401 - fixture
from tests.model_gateway.inbound_gateway_support import gateway_setup  # noqa: F401 - fixture
from tests.model_gateway.model_gateway_openai_responses_support import responses_setup  # noqa: F401 - fixture

#: These tests call provider drivers directly: they run as the platform (``tests/support/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")

UNFINISHED_SAMPLE = "10.11.0.1 is internal"


def _candidate_limit(monkeypatch) -> None:
    def find(_text, _detectors):
        raise CandidateLimitError()

    monkeypatch.setattr(scanner, "_find", find)


def _deadline(monkeypatch) -> None:
    real = scanner._find
    clock = {"now": 0.0}

    def find(text, detectors):
        found = real(text, detectors)
        clock["now"] += 3600.0
        return found

    monkeypatch.setattr(scanner, "time", types.SimpleNamespace(perf_counter=lambda: clock["now"]))
    monkeypatch.setattr(scanner, "_find", find)


CAUSES = {"candidate_limit": _candidate_limit, "deadline": _deadline}


@pytest.fixture(params=sorted(CAUSES))
def unfinished(request, monkeypatch):
    CAUSES[request.param](monkeypatch)
    set_policy_runtime(PolicyRuntime())


def test_a_report_has_no_third_state():
    with pytest.raises(ValueError):
        ScanReport(scanned=True, complete=True, unfinished=True)
    with pytest.raises(ValueError):
        ScanReport(scanned=True, complete=True, unreadable=True)
    with pytest.raises(ValueError):
        ScanReport(scanned=True, complete=False)
    assert not ScanReport(scanned=True, complete=False, unfinished=True, unreadable=True).complete


def test_the_media_exemption_is_finished_and_a_deadline_overrun_is_not(monkeypatch):
    set_policy_runtime(PolicyRuntime())
    media = examine([Segment("", "document", readable=False)], DetectorSet())
    assert media.finished and not media.report.complete and media.report.unreadable
    assert not media.report.unfinished and media.permits(True)

    _deadline(monkeypatch)
    overrun = examine_text("mail a.person@example.com", "prompt", DetectorSet())
    assert overrun.report.total and overrun.report.unfinished and not overrun.report.complete
    assert not overrun.finished and not overrun.permits(True)
    assert overrun.disposition(allowed=True, incomplete=DISPOSITION_WITHHOLD) == DISPOSITION_WITHHOLD
    with pytest.raises(IncompleteExaminationError):
        overrun.clean_entry("x")
    mixed = examine([Segment("", "document", readable=False), Segment("text", "prompt")], DetectorSet())
    assert not mixed.finished and mixed.report.unreadable and mixed.report.unfinished
    assert mixed.report.summary()["unfinished"] is True and mixed.report.summary()["unreadable"] is True


def test_an_examination_cannot_be_built_or_cleaned_around_the_factory(unfinished):
    examination = examine_text(UNFINISHED_SAMPLE, "prompt", DetectorSet())
    with pytest.raises(TypeError):
        Examination(examination.report, DOMAIN_TEXT, object())
    with pytest.raises(TypeError):
        CleanEntry(examination, ("x",), object())
    with pytest.raises(TypeError):
        CleanCache(4).remember(("text", "x"))  # type: ignore[arg-type]
    assert not examination.finished and not examination.report.complete
    assert examination.permits(True) is False
    assert examination.disposition(allowed=True, incomplete=DISPOSITION_WITHHOLD) == DISPOSITION_WITHHOLD
    with pytest.raises(ValueError):
        examination.disposition(allowed=True, incomplete=DISPOSITION_ALLOW)
    with pytest.raises(IncompleteExaminationError):
        examination.clean_entry("x")
    assert not compose([examination], domain=DOMAIN_FIELDS).finished


def test_an_examination_and_its_clean_proof_are_immutable():
    set_policy_runtime(PolicyRuntime())
    clean = examine_text("clean", "prompt", DetectorSet())
    entry = clean.clean_entry("digest")
    for target, name, value in ((clean, "report", ScanReport(scanned=False, complete=True)),
                                (clean, "domain", DOMAIN_FIELDS), (entry, "key", (DOMAIN_FIELDS, "digest")),
                                (entry, "examination", clean)):
        with pytest.raises(AttributeError):
            setattr(target, name, value)
        with pytest.raises(AttributeError):
            delattr(target, name)


def test_the_clean_cache_checks_the_proof_not_only_the_type():
    set_policy_runtime(PolicyRuntime())
    cache = CleanCache(4)
    entry = examine_text("clean", "prompt", DetectorSet()).clean_entry("digest")
    object.__setattr__(entry, "key", (DOMAIN_FIELDS, "digest"))  # forged past the immutability: domain mismatch
    with pytest.raises(IncompleteExaminationError):
        cache.remember(entry)
    dirty = examine_text("mail a.person@example.com", "prompt", DetectorSet())
    forged = examine_text("clean", "prompt", DetectorSet()).clean_entry("digest")
    object.__setattr__(forged, "examination", dirty)
    with pytest.raises(IncompleteExaminationError):
        cache.remember(forged)
    with pytest.raises(ValueError):
        cache.holds("unknown", "digest")
    assert not len(cache)


def test_clean_entries_are_kept_apart_by_domain():
    set_policy_runtime(PolicyRuntime())
    cache = CleanCache(4)
    cache.remember(examine_text("clean", "prompt", DetectorSet()).clean_entry("digest"))
    assert cache.holds(DOMAIN_TEXT, "digest") and not cache.holds(DOMAIN_FIELDS, "digest")
    assert not cache.holds(DOMAIN_STRUCTURED, "digest")


def test_a_memoized_examination_is_recorded_under_the_callers_source(monkeypatch):
    from app.services.content_detection.request_examination import RequestExaminer
    from app.services.content_security.transport import TransportRun

    set_policy_runtime(PolicyRuntime())
    calls = {"count": 0}
    real = scanner._find

    def find(text, detectors):
        calls["count"] += 1
        return real(text, detectors)

    monkeypatch.setattr(scanner, "_find", find)
    text = "mail a.person@example.com"
    examiner = RequestExaminer(DetectorSet(builtin=frozenset({"email"})), RequestBudget())
    run = TransportRun(examiner, frozenset({"email"}))
    assert run.text(text) != text
    for source in ("prompt", "system", "tool_result", "output"):
        report = examiner.report([Segment(text, source)], frozenset({"email"})).report
        assert report.sources == (source,) and report.segment_sources == (source,)
    assert calls["count"] == 1


async def test_the_provider_wrapper_records_the_prompt_as_the_prompt(monkeypatch):
    from app.services.content_security import model_call_outcome as model_call
    from tests.content_security.test_model_call_drivers import _AnyDriver

    set_policy_runtime(PolicyRuntime())
    recorded: list[dict] = []
    monkeypatch.setattr(model_call, "record_decision", recorded.append)
    driver = _AnyDriver({"content": "Done."})
    await driver.chat(messages=[{"role": "user", "content": "mail a.person@example.com"}], model="m")
    (entry,) = recorded
    assert entry["content"]["sources"] == ["prompt"]


TEXT = "deploy notes for 10.11.0.1"


async def _transport(fx):
    from app.services.content_detection.request_examination import RequestExaminer
    from app.services.content_security.transport import TransportRun

    run = TransportRun(RequestExaminer(DetectorSet(builtin=frozenset({"internal_ip"})), RequestBudget()), frozenset())
    assert run.text(TEXT, "tool_result") == WITHHELD_TEXT and run.withheld == 1
    (examination,) = run.examinations
    assert not examination.finished and examination.report.segment_sources == ("tool_result",)


async def _request_examination(fx):
    from app.services.content_detection.request_examination import RequestExaminer

    examiner = RequestExaminer(DetectorSet(), RequestBudget())
    assert not examiner.examine(TEXT, "prompt").finished, "never finished"
    assert not examiner.examine(TEXT, "history").finished, "the memo keeps it unfinished"
    assert not examiner.report([Segment(TEXT, "prompt")], frozenset({"internal_ip"})).finished


async def _model_call_fields(fx):
    from app.services.content_detection.request_examination import RequestExaminer
    from app.services.content_security.format_chat_messages import provider_messages
    from app.services.content_security.handling import SURFACE_PLATFORM, plan_for
    from app.services.content_security.model_call_fields import RecordedRun, Reports, refusing, reports

    run = RecordedRun(RequestExaminer(DetectorSet(), RequestBudget()), frozenset())
    copy = provider_messages([{"role": "user", "content": TEXT, "name": TEXT}], run)
    # The extra is read with its key: both the name and the value were not fully examined.
    assert TEXT not in json.dumps(copy) and run.withheld_at == {"messages": 1, "message_extras": 2}
    plan = plan_for({"internal_ip": "refuse"}, SURFACE_PLATFORM)
    injection, refused, per_surface = refusing(run, plan)
    assert not injection.detected and not refused.detected and per_surface == {}, "partial findings refuse nothing"
    assert reports(run, plan, "scope") == Reports({}, {}) and run.detected() == {}


async def _model_call(fx):
    from app.services.content_security.refusal import ContentPolicyRefusedError
    from tests.content_security.test_model_call_drivers import _AnyDriver

    driver = _AnyDriver({"content": TEXT, "thinking": TEXT})
    with pytest.raises(ContentPolicyRefusedError) as refused:  # the final check of the withheld copy is unfinished too
        await driver.chat(messages=[{"role": "user", "content": TEXT}], model="m")
    assert driver.sent == [] and refused.value.content_notice["reason"] == "content_scan_unfinished"


async def _decision(fx):
    from app.services.content_routing.decision import decide_model_content, scan_for
    from app.services.policy_engine.shadow import LegacyDecision

    scans = scan_for([Segment(TEXT, "prompt")], "ws-1")
    decision = decide_model_content(route="seat", alias="m", scans=scans, workspace_id="ws-1",
                                    builtin_check=LegacyDecision(True))
    assert not decision.allowed and decision.refusal == "content_scan_unfinished"


async def _chat(fx):
    from app.services.model_gateway.litellm.errors import LiteLLMGatewayError
    from tests.content_detection.test_examination_boundaries import _chat as governed_chat

    with pytest.raises(LiteLLMGatewayError) as refused:
        await governed_chat([{"role": "user", "content": TEXT}])
    assert refused.value.denial_reason == "content_scan_unfinished"


async def _tool_results(fx):
    from app.services.content_routing.tool_results import check_tool_result

    outcome = await check_tool_result({"text": TEXT}, tool_name="t", family=None, origin="connector",
                                      workspace_id="ws-1", session_id=None, conversation="chat")
    assert outcome.blocked and outcome.reason == "content_scan_unfinished"
    assert TEXT not in json.dumps(outcome.result)


async def _client_tool_results(fx):
    from app.services.content_routing.client_tool_results import client_tool_result_denial
    from app.services.content_security.format_request_body import examine_request_body
    from tests.content_detection.test_tool_results import MASK_RESULTS, _history_body
    from tests.policy_engine_support import use_custom_policies

    use_custom_policies(MASK_RESULTS, mode="enforce")
    results = examine_request_body(_history_body(TEXT), "ws-1", RequestBudget()).tool_results
    assert results and not any(item.finished for item in results.values())
    denial = client_tool_result_denial(results, workspace_id="ws-1", principal=None)
    assert denial is not None, "an unfinished tool result is never permitted"


async def _enforcement_inbound(fx):
    from tests.model_gateway.conftest import ALIAS
    from tests.model_gateway.test_inbound_anthropic_gateway import ROUTE, _request_body

    body = {**_request_body(), "model": ALIAS}
    body["messages"][0]["content"] = TEXT
    fake, build = fx.gateway
    response = await fx.client.post(ROUTE, json=body, headers=await build())
    assert response.status_code == 400 and "content_scan_unfinished" in response.text
    assert fake.requests == []


async def _openai_service(fx):
    from tests.model_gateway import model_gateway_openai_responses_support as openai_support

    fake, build = fx.responses
    response = await fx.client.post(openai_support.ROUTE, json=openai_support._body(newest=TEXT), headers=await build())
    assert response.status_code == 400 and response.json()["error"]["code"] == "content_scan_unfinished"
    assert fake.requests == []


async def _codex_seat(fx):
    from tests.model_gateway import codex_seat_support

    _workspace_id, _user, gateway, credential = await codex_seat_support._codex_session(fx.client, fx.db)
    response = await fx.client.post(codex_seat_support.ROUTE, json=codex_seat_support._body(newest=TEXT),
                                 headers=codex_seat_support._headers(gateway, credential))
    assert (response.status_code, codex_seat_support._reason(response)) == (400, "content_scan_unfinished")
    assert fx.chatgpt.requests == []


async def _request_body(fx):
    from app.services.content_routing import gateway, gateway_outcome
    from app.services.content_security import format_request_body

    kinds = frozenset({"internal_ip"})
    masked = format_request_body.mask_gateway_body({"messages": [{"role": "user", "content": TEXT}]},
                                                   DetectorSet(builtin=kinds), kinds, RequestBudget())
    assert masked.withheld == 1 and TEXT not in json.dumps(masked.body), "unexamined text is never sent"

    entries: list[dict] = []
    fx.monkeypatch.setattr(gateway_outcome, "record_decision", entries.append)
    outcome = gateway_outcome.GatewayOutcome()
    outcome.bind(route="governed", workspace_id="ws-1", session_id="s", user_id="u", alias="m")
    # A tool declaration and a reasoning summary are part of the whole body, and never cached clean.
    body = {"tools": [{"type": "function", "name": "x", "description": TEXT}],
            "input": [{"type": "reasoning", "summary": [{"type": "summary_text", "text": TEXT}]},
                      {"type": "function_call_output", "call_id": "c", "output": TEXT},
                      {"type": "message", "role": "user", "content": "next"}]}
    scanned = format_request_body.examine_request_body(body, "ws-1", RequestBudget())
    assert not scanned.finished and not scanned.body.live.finished
    assert not any(item.finished for item in scanned.tool_results.values()), "the tool results too"
    refused = gateway.fixed_refusal(scanned, outcome, scanned.finished)
    assert refused is not None and refused.reason == "content_scan_unfinished"
    outcome.write()
    (entry,) = entries
    assert entry["content"]["unfinished"] is True and "detected" not in entry["content"]


async def _seat(fx):
    from app.services.model_gateway.inbound import seat_upstream
    from tests.agent_gateway.seat_presence_support import SEAT, _seat_headers, _seat_session
    from tests.agent_gateway.seat_upstream_support import FakeAnthropic

    fake = FakeAnthropic()
    fx.monkeypatch.setattr(seat_upstream, "seat_transport", lambda: httpx.MockTransport(fake.handle))
    _workspace, _user, gateway, credential = await _seat_session(fx.client, fx.db)
    body = {"model": "claude-sonnet-5", "max_tokens": 16, "messages": [{"role": "user", "content": TEXT}]}
    response = await fx.client.post(SEAT, json=body, headers=_seat_headers(gateway, credential))
    assert response.status_code == 400 and response.headers["x-octryx-gateway-reason"] == "content_scan_unfinished"
    assert fake.requests == []


async def _chat_messages(fx):
    from app.services.content_security.format_chat_messages import mask_chat_messages

    masked = mask_chat_messages([{"role": "user", "content": TEXT}], DetectorSet(), frozenset({"email"}), None)
    assert masked.body[0]["content"] == WITHHELD_TEXT and masked.withheld == 1


async def _message_trust(fx):
    from app.services.content_security.message_trust import without_role_phrasing

    examination = examine_text(TEXT, "system", DetectorSet())
    assert not without_role_phrasing(examination, [Segment(TEXT, "system")]).finished


async def _command(fx):
    from app.services.security_analyzer.content_command import content_command_analyzer

    assert (await content_command_analyzer("run", f"ping {TEXT}", None)).action == "review"


async def _preview(fx):
    from app.services.content_detection.preview import preview

    answer = preview(TEXT, DetectorSet())
    assert answer["unfinished"] is True and TEXT not in answer["masked_text"]


#: consumer module → its property case (each asserts its own boundary).
CASES = {
    "app.services.content_security.transport": _transport,
    "app.services.content_security.model_call": _model_call,
    "app.services.content_security.enforcement_call": _model_call,
    "app.services.content_security.model_call_fields": _model_call_fields,
    "app.services.content_detection.request_examination": _request_examination,
    "app.services.content_routing.decision": _decision,
    "app.services.content_routing.chat": _chat,
    "app.services.content_routing.tool_results": _tool_results,
    "app.services.content_routing.client_tool_results": _client_tool_results,
    "app.services.content_security.enforcement_inbound": _enforcement_inbound,
    "app.services.model_gateway.inbound.openai_service": _openai_service,
    "app.services.model_gateway.inbound.codex_seat": _codex_seat,
    "app.services.model_gateway.inbound.seat": _seat,
    "app.services.content_security.format_chat_messages": _chat_messages,
    "app.services.content_security.format_request_body": _request_body,
    "app.services.content_security.message_trust": _message_trust,
    "app.services.security_analyzer.content_command": _command,
    "app.services.content_detection.preview": _preview,
    "app.api.routes.agent_gateway.agent_gateway": launcher_route_case,
    "octryx_claude.content_hooks": launcher_disposition_case,
    "octryx_claude.post_tool_use_hook": launcher_hook_case,
    **BOUNDARY_CASES,
    **FINAL_CASES,
}


#: Every case: one per consumer module, and one per result-consuming edge its module's case does not reach
#: (``test_examination_guard.EDGES``).
ALL_CASES = {**CASES, **EDGE_CASES}
#: The cases that read the forwarded ``/openai`` Responses request (its upstream replaces the Anthropic one).
RESPONSES_CASES = frozenset({"app.services.model_gateway.inbound.openai_service"})


@pytest.mark.parametrize("consumer", sorted(set(ALL_CASES) - RESPONSES_CASES))
@pytest.mark.asyncio
async def test_an_unfinished_examination_never_allows_caches_or_forwards(
        client, db, tmp_path, monkeypatch, unfinished, gateway_setup, chatgpt, consumer):  # noqa: F811
    await ALL_CASES[consumer](types.SimpleNamespace(client=client, db=db, tmp_path=tmp_path, monkeypatch=monkeypatch,
                                                    gateway=gateway_setup, chatgpt=chatgpt))


@pytest.mark.parametrize("consumer", sorted(RESPONSES_CASES))
@pytest.mark.asyncio
async def test_an_unfinished_responses_examination_never_forwards(
        client, db, monkeypatch, unfinished, responses_setup, consumer):  # noqa: F811
    await ALL_CASES[consumer](types.SimpleNamespace(client=client, db=db, monkeypatch=monkeypatch,
                                                    responses=responses_setup))
