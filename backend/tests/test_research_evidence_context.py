"""Actual current read provenance survives the real pre-dispatch compaction seam."""
from __future__ import annotations

import copy
import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent.engine.pre_dispatch._history_invariant_normalization import normalize_pre_dispatch_history
from app.agent.engine.pre_dispatch._pre_dispatch_runtime_guard import prepare_pre_dispatch_runtime_messages
from app.agent.engine.pre_dispatch._research_evidence_binding import research_evidence_context
from app.agent.engine.pre_dispatch._research_evidence_context import ResearchEvidenceContextError
from app.models import FlowDefinition, LLMModel, LLMProvider, Message, Session, UserProject
from app.models.project.knowledge_evidence import KnowledgeEvidenceSpan, KnowledgeSourceHead
from app.models.project.knowledge_source_acl import KnowledgeSourceAcl
from app.services.tool_artifact.summary import build_tool_artifact_envelope, serialize_tool_artifact_envelope
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY as RESOLUTION
from app.services.workflow_runs.binding import phase_resolution
from app.services.workflow_runs.graph import parse_phased_definition
from app.services.workflow_runs.phase_contract import phase_definition
from app.tools.context import ToolContext
from tests.phased_workflow_fixtures import publish_phased
from tests.specification_definition_support import specification_definition
from tests.specification_producer_support import producer

pytestmark = pytest.mark.asyncio


async def prepared(db, *, count=4, passage_chars=1800):
    run, actor, session, source, revision, call, _, _ = await producer(db, complete=False)
    await db.delete(call)
    key = await publish_phased(db, specification_definition())
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == key))).scalar_one()
    run.flow_definition_version_id, run.workflow_key = flow.current_version_id, key
    run.status, run.waiting_kind = "running", None
    graph = parse_phased_definition(specification_definition())
    resolution = phase_resolution(run=run, node_id="research", definition=phase_definition(run, graph.nodes["research"]))
    context = ToolContext(user_id=actor.id, project_ids=[run.project_id], roles=[], session_id=session.id,
                          project_config={}, db=db, request_id="current-research-turn")
    provider = LLMProvider(name="research-capacity-fixture", provider_family="bedrock", config_json={})
    db.add(provider)
    await db.flush()
    model = LLMModel(provider_id=provider.id, model_id="claude-haiku-5-5", context_length=30000)
    db.add(model)
    runtime = {"provider_id": provider.id, "model": model.model_id}
    messages = [{"role": "system", "content": "Governed system contract. " * 350},
                {"role": "user", "content": "Read the current evidence, then submit the research brief."}]
    calls, spans = [], []
    from app.models import ToolCall
    for index in range(count):
        evidence_key = revision.id.replace("-", "") + f":{index + 2}"
        text = (f"Current passage {index}: " + "x" * passage_chars)
        span = KnowledgeEvidenceSpan(project_id=run.project_id, revision_id=revision.id, span_ordinal=index + 2,
            evidence_key=evidence_key, citation=f"Passage {index}", char_start=0, char_end=len(text), text=text)
        db.add(span)
        provider_id = f"read-{index}"
        tool_call = {"id": provider_id, "type": "function", "function": {
            "name": "knowledge_read", "arguments": json.dumps({"evidence_key": evidence_key, "window": 0})}}
        assistant = Message(session_id=session.id, role="assistant", content="Read current evidence.",
                            tool_calls=[tool_call])
        db.add(assistant)
        await db.flush()
        result = {"state": "ok", "evidence_key": evidence_key, "text": text, "current": True}
        row = ToolCall(session_id=session.id, message_id=assistant.id, tool_name="knowledge_read",
            request_id=context.request_id, status="success", parameters={"evidence_key": evidence_key, "window": 0},
            result=result)
        db.add(row)
        await db.flush()
        messages.extend([{"role": "assistant", "content": assistant.content, "tool_calls": [tool_call]},
            {"role": "tool", "tool_call_id": provider_id, "content": serialize_tool_artifact_envelope(
                build_tool_artifact_envelope(artifact_id=row.id, tool_name="knowledge_read", payload=result,
                                             include_result=True))},
            {"role": "assistant", "content": "Unneeded intermediate narration. " * 300}])
        calls.append(row)
        spans.append(span)
    await db.flush()
    return SimpleNamespace(run=run, actor=actor, session=session, source=source, revision=revision, model=model,
        runtime=runtime, calls=calls, spans=spans, messages=messages, context=context, metadata={RESOLUTION: resolution})


async def dispatch(db, case, **kwargs):
    protected = await research_evidence_context(db=db, tool_context=case.context, session_metadata=case.metadata,
        messages=case.messages, runtimes=[case.runtime], tools=kwargs.get("tools", []), max_tokens=1024)
    return prepare_pre_dispatch_runtime_messages(messages=case.messages, runtimes=[case.runtime], max_tokens=1024,
        reasoning_effort=None, research_context=protected)


def read_ids(messages):
    return {m["tool_call_id"] for m in messages if m.get("role") == "tool"}


async def test_four_successful_actual_current_reads_survive_real_compaction_with_exact_pairs(db):
    case = await prepared(db)
    before = copy.deepcopy(case.messages)
    legacy = prepare_pre_dispatch_runtime_messages(messages=case.messages, runtimes=[case.runtime],
                                                   max_tokens=1024, reasoning_effort=None)
    assert len(read_ids(legacy.messages)) < 4  # Reproduces the loss, independent of provider prose.
    result = await dispatch(db, case)
    assert read_ids(result.messages) == {"read-0", "read-1", "read-2", "read-3"}
    assert all(span.text in json.dumps(result.messages) for span in case.spans)
    assert result.messages[:2] == case.messages[:2]
    assert not normalize_pre_dispatch_history(result.messages)[1].requires_normalization
    assert case.messages == before
    assert result.compaction_plan.reason == "current_research_evidence_retained"


async def test_repeated_reads_keep_one_latest_pair_per_key_and_do_not_inflate_source_bounds(db):
    case = await prepared(db)
    from app.models import ToolCall
    old = case.calls[0]
    provider_call = {"id": "read-again", "function": {"name": "knowledge_read",
                     "arguments": json.dumps(old.parameters)}}
    assistant = Message(session_id=case.session.id, role="assistant", content="Repeated read.", tool_calls=[provider_call])
    db.add(assistant)
    await db.flush()
    row = ToolCall(session_id=case.session.id, message_id=assistant.id, tool_name="knowledge_read",
        request_id=case.context.request_id, parameters=old.parameters, result=old.result, status="success")
    db.add(row)
    await db.flush()
    case.messages += [{"role": "assistant", "content": assistant.content, "tool_calls": [provider_call]},
        {"role": "tool", "tool_call_id": "read-again", "content": serialize_tool_artifact_envelope(
            build_tool_artifact_envelope(artifact_id=row.id, tool_name="knowledge_read", payload=row.result,
                                         include_result=True))}]
    result = await dispatch(db, case)
    assert read_ids(result.messages) == {"read-again", "read-1", "read-2", "read-3"}
    assert not normalize_pre_dispatch_history(result.messages)[1].requires_normalization


@pytest.mark.parametrize("foreign", ["request", "session", "old_pass", "failed", "unsuccessful_result", "historical_result"])
async def test_foreign_old_or_unsuccessful_reads_are_never_protected(db, foreign):
    case = await prepared(db)
    call = case.calls[0]
    if foreign == "request":
        call.request_id = "another-turn"
    elif foreign == "session":
        other = Session(user_id=case.actor.id, project_id=case.run.project_id)
        db.add(other)
        await db.flush()
        call.session_id = other.id
    elif foreign == "old_pass":
        call.created_at -= timedelta(days=1)
    elif foreign == "failed":
        call.status = "error"
    elif foreign == "historical_result":
        call.result = {**call.result, "current": False}
    else:
        call.result = {"state": "not_found"}
    await db.flush()
    result = await dispatch(db, case)
    assert read_ids(result.messages) == {"read-1", "read-2", "read-3"}
    assert case.spans[0].text not in json.dumps(result.messages)


@pytest.mark.parametrize("drift", ["actor", "pass", "request", "head", "acl", "artifact", "pair", "capacity", "fit",
                                   "input_args", "old_assistant", "missing_model_text", "membership"])
async def test_unproven_current_context_holds_before_provider_or_provenance_changes(db, drift):
    case = await prepared(db)
    if drift == "actor":
        case.context.user_id = str(uuid4())
    elif drift == "pass":
        case.run.node_state = {**case.run.node_state, "entry": case.run.node_state["entry"] + 1}
    elif drift == "request":
        case.context.request_id = None
    elif drift == "head":
        (await db.get(KnowledgeSourceHead, case.source.id)).wanted_revision_id = None
    elif drift == "membership":
        membership = (await db.execute(select(UserProject).where(UserProject.user_id == case.actor.id,
            UserProject.project_id == case.run.project_id))).scalar_one()
        await db.delete(membership)
    elif drift == "acl":
        db.add(KnowledgeSourceAcl(project_id=case.run.project_id, source_key=case.source.source_key,
                                  restriction="restricted"))
    elif drift == "artifact":
        row = case.calls[0]
        row.message_id = None
    elif drift == "pair":
        case.messages = [m for m in case.messages if m.get("tool_call_id") != "read-0"]
    elif drift == "capacity":
        case.model.context_length = None
    elif drift == "input_args":
        case.messages[2]["tool_calls"][0]["function"]["arguments"] = json.dumps({"evidence_key": "foreign"})
    elif drift == "old_assistant":
        assistant = await db.get(Message, case.calls[0].message_id)
        assistant.created_at -= timedelta(days=1)
    elif drift == "missing_model_text":
        envelope = json.loads(case.messages[3]["content"])
        del envelope["result"]["text"]
        case.messages[3]["content"] = json.dumps(envelope)
    else:
        case.model.context_length = 2500
    await db.flush()
    before = copy.deepcopy((case.run.context, case.run.node_state, case.run.loop_counters))
    with pytest.raises(ResearchEvidenceContextError) as error:
        await dispatch(db, case)
    assert error.value.code == "needs_configuration"
    assert "Current passage" not in str(error.value)
    assert (case.run.context, case.run.node_state, case.run.loop_counters) == before


@pytest.mark.parametrize("count,chars", [(9, 10), (4, 7900), (1, 8001)])
async def test_distinct_key_and_aggregate_source_bounds_are_closed(db, count, chars):
    case = await prepared(db, count=count, passage_chars=chars)
    with pytest.raises(ResearchEvidenceContextError):
        await dispatch(db, case)


async def test_tool_schema_and_completion_are_reserved_inside_real_capacity(db):
    case = await prepared(db)
    with pytest.raises(ResearchEvidenceContextError):
        await dispatch(db, case, tools=[{"function": {"name": "large_schema", "description": "schema" * 30000}}])


async def test_chat_and_nonresearch_phases_retain_original_predispatch_behavior_without_capacity_lookup(db):
    case = await prepared(db)
    case.metadata = {}
    case.model.context_length = None
    protected = await research_evidence_context(db=db, tool_context=case.context, session_metadata=case.metadata,
        messages=case.messages, runtimes=[case.runtime], tools=[], max_tokens=1024)
    assert protected is None
    old = prepare_pre_dispatch_runtime_messages(messages=case.messages, runtimes=[case.runtime],
                                               max_tokens=1024, reasoning_effort=None)
    new = prepare_pre_dispatch_runtime_messages(messages=case.messages, runtimes=[case.runtime],
                                               max_tokens=1024, reasoning_effort=None, research_context=protected)
    assert new == old


async def test_only_guardrail_sanitized_pair_is_retained_never_raw_ledger_text(db):
    case = await prepared(db)
    envelope = json.loads(case.messages[3]["content"])
    envelope["result"]["text"] = "[Guardrail-sanitized current evidence]"
    case.messages[3]["content"] = json.dumps(envelope)
    result = await dispatch(db, case)
    assert read_ids(result.messages) == {"read-0", "read-1", "read-2", "read-3"}
    shown = json.dumps(result.messages)
    assert "[Guardrail-sanitized current evidence]" in shown
    assert case.spans[0].text not in shown


async def test_unknown_unused_fallback_does_not_block_primary_but_is_held_if_reached(db):
    from app.agent.engine.pre_dispatch._research_evidence_context import research_attempt_guard

    case = await prepared(db)
    unknown = {**case.runtime, "model": "unverified-fallback", "target_id": str(uuid4())}
    context = await research_evidence_context(db=db, tool_context=case.context, session_metadata=case.metadata,
        messages=case.messages, runtimes=[case.runtime, unknown], tools=[], max_tokens=1024)
    result = prepare_pre_dispatch_runtime_messages(messages=case.messages, runtimes=[case.runtime, unknown],
        max_tokens=1024, reasoning_effort=None, research_context=context)
    guard = research_attempt_guard(context, result.messages)
    guard(case.runtime, result.messages)
    with pytest.raises(ResearchEvidenceContextError) as error:
        guard(unknown, result.messages)
    assert error.value.reason == "research_context_capacity_unavailable"


@pytest.mark.parametrize("change", ["text", "arguments", "missing", "orphan", "over_budget"])
async def test_actual_retry_must_preserve_exact_sanitized_read_pairs_and_runtime_capacity(db, change):
    from app.agent.engine.pre_dispatch._research_evidence_context import research_attempt_guard

    case = await prepared(db)
    context = await research_evidence_context(db=db, tool_context=case.context, session_metadata=case.metadata,
        messages=case.messages, runtimes=[case.runtime], tools=[], max_tokens=1024)
    result = prepare_pre_dispatch_runtime_messages(messages=case.messages, runtimes=[case.runtime],
        max_tokens=1024, reasoning_effort=None, research_context=context)
    guard = research_attempt_guard(context, result.messages)
    attempt = copy.deepcopy(result.messages)
    if change == "text":
        target = next(m for m in attempt if m.get("tool_call_id") == "read-0")
        envelope = json.loads(target["content"])
        envelope["result"]["text"] = "truncated"
        target["content"] = json.dumps(envelope)
    elif change == "arguments":
        target = next(m for m in attempt if m.get("tool_calls"))
        target["tool_calls"][0]["function"]["arguments"] = "{}"
    elif change == "missing":
        attempt = [m for m in attempt if m.get("tool_call_id") != "read-0"]
    elif change == "orphan":
        attempt.append({"role": "tool", "tool_call_id": "orphan", "content": "{}"})
    else:
        attempt.append({"role": "user", "content": "too large" * 30000})
    with pytest.raises(ResearchEvidenceContextError):
        guard(case.runtime, attempt)
