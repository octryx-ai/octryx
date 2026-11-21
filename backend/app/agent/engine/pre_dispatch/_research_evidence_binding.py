"""Resolve a protected research working set from actual current server rows, never model-authored proof."""
from __future__ import annotations

import asyncio
import json

from fastapi import HTTPException
from sqlalchemy import select

from ....models import LLMModel, Message, Session, ToolCall, User, WorkflowRun, WorkflowRunEvent
from ....models.project.knowledge_evidence import KnowledgeEvidenceSpan, KnowledgeSourceHead, KnowledgeSourceRevision
from ....services.knowledge.access.authorization import authorize_workspace
from ....services.knowledge.ledger.errors import EvidenceLedgerError
from ....services.knowledge.ledger.reading import read_span_window
from ....services.token_estimation import estimate_serialized_tokens
from ....services.tool_artifact.summary import parse_tool_artifact_envelope
from ....services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from ....services.workflow_runs.graph import graph_for_run
from ....services.workflow_runs.phase_outputs import phase_output
from ....services.workflow_runs.records import main_session_id
from ....services.workflow_runs.states import RUN_RESOLUTION_KEY
from ....time_utils import ensure_utc
from ._pre_dispatch_compaction import _resolve_completion_tokens
from ._research_evidence_context import ResearchEvidenceContext, ResearchEvidenceContextError, runtime_context_key


def _hold(reason):
    raise ResearchEvidenceContextError(reason)


async def _payload(db, call):
    result = call.result
    if isinstance(result, dict) and result.get("_artifact_storage"):
        from ....services.artifact_store import load_tool_artifact_record, read_tool_artifact_payload

        artifact = await load_tool_artifact_record(db, artifact_id=call.id)
        if artifact is None or artifact.session_id != call.session_id or artifact.tool_name != "knowledge_read":
            _hold("read_artifact_unavailable")
        try:
            result = await asyncio.to_thread(read_tool_artifact_payload, artifact)
        except (OSError, ValueError, RuntimeError):
            _hold("read_artifact_unavailable")
    return result


async def _budget(db, runtimes, tools, max_tokens):
    budgets = {}
    for index, runtime in enumerate(runtimes):
        model = (await db.execute(select(LLMModel).where(
            LLMModel.provider_id == runtime.get("provider_id"), LLMModel.model_id == runtime.get("model"))
            .execution_options(populate_existing=True))).scalar_one_or_none()
        if model is None or type(model.context_length) is not int or model.context_length <= 0:
            if index == 0:
                _hold("research_context_capacity_unavailable")
            continue
        completion = _resolve_completion_tokens(runtime, max_tokens=max_tokens)
        schema_tokens = estimate_serialized_tokens(tools or [])
        # Conservative headroom stays inside the real catalog capacity, including schemas and completion.
        budgets[runtime_context_key(runtime)] = int(model.context_length * 0.9) - completion - schema_tokens
    if not budgets or min(budgets.values()) <= 0:
        _hold("research_context_capacity_unavailable")
    return min(budgets.values()), tuple(budgets.items())


async def research_evidence_context(*, db, tool_context, session_metadata, messages, runtimes, tools, max_tokens):
    """Return None for every historical/non-research path; no Run/event/provenance mutation or dispatch."""
    resolution = session_metadata.get(ROUTING_RESOLUTION_KEY)
    resolution = resolution if isinstance(resolution, dict) else {}
    contract = resolution.get("workflow_contract")
    contract = contract if isinstance(contract, dict) else {}
    phase = contract.get("workflow_run_phase")
    output = phase.get("output") if isinstance(phase, dict) else None
    if not isinstance(output, dict) or output.get("kind") != "research_brief":
        return None
    marker = resolution.get(RUN_RESOLUTION_KEY)
    if not isinstance(marker, dict):
        _hold("current_research_binding_changed")
    run = await db.get(WorkflowRun, marker.get("run_id"), populate_existing=True) if marker.get("run_id") else None
    actor = await db.get(User, tool_context.user_id, populate_existing=True)
    session = await db.get(Session, tool_context.session_id, populate_existing=True)
    request = tool_context.request_id
    if (run is None or actor is None or not actor.is_active or not session or session.user_id != actor.id
            or session.project_id != run.project_id or run.requested_by != actor.id or not request
            or run.status != "running" or run.current_node_id != marker.get("node_id")
            or dict(run.node_state or {}).get("entry") != marker.get("entry")
            or await main_session_id(db, run) != session.id):
        _hold("current_research_binding_changed")
    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id)
    if node is None or node.kind != "phase" or phase_output(node) != "research_brief":
        _hold("current_research_binding_changed")
    entered = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id,
        WorkflowRunEvent.node_id == run.current_node_id, WorkflowRunEvent.kind == "node_entered")
        .order_by(WorkflowRunEvent.created_at.desc(), WorkflowRunEvent.id.desc()).limit(1))).scalar_one_or_none()
    if entered is None or dict(entered.detail or {}).get("entry") != marker["entry"]:
        _hold("current_research_binding_changed")
    try:
        authorized = await authorize_workspace(db, current_user=actor, workspace_id=run.project_id)
    except (HTTPException, EvidenceLedgerError):
        _hold("current_read_authority_unavailable")
    calls = (await db.execute(select(ToolCall).where(ToolCall.session_id == session.id, ToolCall.request_id == request,
        ToolCall.tool_name == "knowledge_read", ToolCall.status == "success")
        .order_by(ToolCall.created_at, ToolCall.id).execution_options(populate_existing=True))).scalars().all()
    latest = {}
    for call in calls:
        if call.created_at is None or ensure_utc(call.created_at) < ensure_utc(entered.created_at):
            continue
        result = await _payload(db, call)
        params = call.parameters if isinstance(call.parameters, dict) else {}
        key = params.get("evidence_key")
        if (isinstance(result, dict) and result.get("state") == "ok" and result.get("current") is True
                and result.get("evidence_key") == key):
            if not isinstance(key, str):
                _hold("read_identity_unavailable")
            latest[key] = call
    if len(latest) > 8:
        _hold("research_evidence_exceeds_bound")
    provider_pairs = {}
    input_calls = {c.get("id"): c for m in messages if m.get("role") == "assistant"
                   for c in m.get("tool_calls") or [] if isinstance(c, dict)}
    for message in messages:
        if message.get("role") != "tool":
            continue
        envelope = parse_tool_artifact_envelope(message.get("content"))
        if envelope and envelope.get("tool_name") == "knowledge_read":
            provider_pairs[envelope["artifact_id"]] = (message.get("tool_call_id"), envelope)
    protected, chars = set(), 0
    for key, call in latest.items():
        pair = provider_pairs.get(call.id)
        assistant = await db.get(Message, call.message_id) if call.message_id else None
        original = next((c for c in assistant.tool_calls or [] if c.get("id") == pair[0]), None) if (
            pair and assistant and assistant.role == "assistant" and assistant.session_id == session.id) else None
        function = dict(original.get("function") or {}) if original else {}
        input_function = dict(input_calls.get(pair[0], {}).get("function") or {}) if pair else {}
        try:
            args = function.get("arguments")
            args = json.loads(args) if isinstance(args, str) else args
            input_args = input_function.get("arguments")
            input_args = json.loads(input_args) if isinstance(input_args, str) else input_args
        except (ValueError, TypeError):
            args = input_args = None
        shown = pair[1].get("result") if pair else None
        if (not original or not assistant.created_at or ensure_utc(assistant.created_at) < ensure_utc(entered.created_at)
                or function.get("name") != "knowledge_read" or not isinstance(args, dict)
                or input_function.get("name") != "knowledge_read" or not isinstance(input_args, dict)
                or input_args != call.parameters or args != call.parameters or not isinstance(shown, dict)
                or shown.get("state") != "ok" or shown.get("evidence_key") != key
                or not isinstance(shown.get("text"), str) or not shown["text"].strip()):
            _hold("current_read_pair_missing")
        try:
            read = await read_span_window(db, authorized=authorized, evidence_key=key,
                                          window=call.parameters.get("window", 1))
        except EvidenceLedgerError:
            _hold("current_read_authority_unavailable")
        span = (await db.execute(select(KnowledgeEvidenceSpan).where(KnowledgeEvidenceSpan.project_id == run.project_id,
            KnowledgeEvidenceSpan.evidence_key == key))).scalar_one_or_none()
        revision = await db.get(KnowledgeSourceRevision, span.revision_id, populate_existing=True) if span else None
        head = (await db.execute(select(KnowledgeSourceHead).where(
            KnowledgeSourceHead.source_id == revision.source_id, KnowledgeSourceHead.current_revision_id == revision.id,
            KnowledgeSourceHead.project_id == run.project_id))).scalar_one_or_none() if revision else None
        if not read.current or not head or head.wanted_revision_id != span.revision_id or not read.text.strip():
            _hold("current_read_authority_unavailable")
        chars += len(read.text)
        if len(read.text) > 8000 or chars > 30000:
            _hold("research_evidence_exceeds_bound")
        protected.add(pair[0])
    capacity, runtime_budgets = await _budget(db, runtimes, tools, max_tokens)
    return ResearchEvidenceContext(frozenset(protected), capacity, chars, runtime_budgets)
