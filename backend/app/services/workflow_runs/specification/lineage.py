"""Server-owned specification lineage and current-principal Knowledge reauthorization.

Call under the existing Run claim. These helpers never commit, impersonate, publish or grant access.
"""
from __future__ import annotations

import copy
import json
import math
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select

from ....models import ToolCall, WorkflowRunDecision, WorkflowRunEvent
from ....models.project.knowledge_evidence import (
    KnowledgeEvidenceSource,
    KnowledgeEvidenceSpan,
    KnowledgeSourceHead,
    KnowledgeSourceRevision,
)
from ....models.project.knowledge_source_acl import KnowledgeSourceAcl, KnowledgeSourceAclPrincipal
from ....time_utils import ensure_utc, utc_now
from ...knowledge.access.authorization import authorize_workspace
from ...knowledge.ledger.errors import EvidenceLedgerError
from ...knowledge.ledger.reading import read_span_window
from ...knowledge.retrieval.contracts import is_valid_evidence_id
from ...knowledge.retrieval.locator import markdown_citation
from ...workflow_checks.evidence import tool_uses
from ..phase_outputs import output_hash, recorded_output
from ..records import WorkflowRunError, main_session_id, record_event
from ..work_roles import active_human, lock_actor_membership, workspace_humans
from .records import KINDS, proposal_from_record, used_keys, validate_proposal

PROVENANCE_EVENT = "specification_read_provenance"


class SpecificationUnavailableError(Exception):
    """Closed non-sensitive reason; never include source text, identifiers or upstream exception text."""

    def __init__(self, reason: str, *, code="needs_configuration") -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code


SpecificationUnavailable = SpecificationUnavailableError


def _hold(reason: str, *, invalid=False):
    raise SpecificationUnavailable(reason, code="invalid_output" if invalid else "needs_configuration")


async def _actor(db, run, principal):
    actor_id = getattr(principal, "id", None)
    if not actor_id:
        _hold("principal_unavailable")
    await lock_actor_membership(db, run.project_id, actor_id)
    actor = await active_human(db, actor_id)
    if actor is None or actor.id not in await workspace_humans(db, run.project_id):
        _hold("principal_unavailable")
    return actor


def effective_budget(run) -> dict:
    budget = dict(run.limits or {}).get("budget")
    keys = {"tokens", "cost_usd", "active_seconds", "tool_calls"}
    if (type(budget) is not dict or set(budget) != keys or any(
            type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in budget.values())):
        _hold("research_budget_unavailable")
    return copy.deepcopy(budget)


def _ref(run, envelope: dict) -> dict:
    return {"kind": envelope["kind"], "version": envelope["version"], "hash": envelope["hash"],
            "parent_run_id": run.id, "node_id": envelope["node_id"], "entry": envelope["entry"]}


async def _envelope(db, run, kind: str) -> dict:
    envelope = recorded_output(run, kind)
    if (not envelope or envelope.get("kind") != kind or type(envelope.get("version")) is not int
            or envelope["version"] < 1 or type(envelope.get("entry")) is not int or envelope["entry"] < 1
            or envelope.get("hash") != output_hash(envelope.get("record"))
            or proposal_from_record(kind, envelope.get("record"))[1]):
        _hold("output_missing_or_changed")
    event = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id,
        WorkflowRunEvent.node_id == envelope.get("node_id"), WorkflowRunEvent.kind == "node_entered")
        .order_by(WorkflowRunEvent.created_at.desc(), WorkflowRunEvent.id.desc()).limit(1))).scalar_one_or_none()
    if event is None or dict(event.detail or {}).get("entry") != envelope["entry"]:
        _hold("producer_pass_changed")
    output = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id,
        WorkflowRunEvent.node_id == envelope["node_id"], WorkflowRunEvent.kind == "phase_output_recorded")
        .order_by(WorkflowRunEvent.created_at.desc(), WorkflowRunEvent.id.desc()))).scalars().all()
    matching = next((row for row in output if dict(row.detail or {}).get("kind") == kind), None)
    if (matching is None or matching.detail.get("hash") != envelope["hash"]
            or matching.detail.get("version") != envelope["version"]):
        _hold("output_provenance_missing")
    return envelope


async def _confirmed(db, run, kind: str) -> dict:
    from ..handoff.authority import confirmed_envelopes

    envelope = await _envelope(db, run, kind)
    try:
        proof = (await confirmed_envelopes(db, run, [kind]))[kind]
    except (WorkflowRunError, HTTPException) as error:
        raise SpecificationUnavailable("upstream_confirmation_unavailable") from error
    return {**_ref(run, envelope), "decision_id": proof["decision_id"], "decision_hash": proof["decision_hash"]}


def _trusted_ids(tool_history) -> list[str]:
    return sorted({use.call_id for use in tool_uses(tool_history or [])
                   if use.name == "knowledge_read" and use.succeeded and use.call_id})


async def _calls(db, run, *, ids, session_id, request_id, node_id, entry):
    if (not ids or len(ids) > 100 or not request_id or session_id != await main_session_id(db, run)):
        _hold("trusted_reads_unavailable")
    entered = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id,
        WorkflowRunEvent.node_id == node_id, WorkflowRunEvent.kind == "node_entered")
        .order_by(WorkflowRunEvent.created_at.desc(), WorkflowRunEvent.id.desc()).limit(1))).scalar_one_or_none()
    if not entered or entered.detail.get("entry") != entry:
        _hold("research_pass_changed")
    calls = (await db.execute(select(ToolCall).where(ToolCall.id.in_(ids))
                             .execution_options(populate_existing=True))).scalars().all()
    shown: dict[str, list[str]] = {}
    if len(calls) != len(ids) or any(c.status != "success" or c.tool_name != "knowledge_read"
            or c.session_id != session_id or c.request_id != request_id or c.created_at is None
            or ensure_utc(c.created_at) < ensure_utc(entered.created_at) for c in calls):
        _hold("trusted_reads_unavailable")
    for call in calls:
        if type(call.result) is not dict or type(call.parameters) is not dict:
            _hold("trusted_reads_unavailable")
        result = dict(call.result)
        if result.get("_artifact_storage"):
            from ...artifact_store import load_tool_artifact_record, read_tool_artifact_payload

            artifact = await load_tool_artifact_record(db, artifact_id=call.id)
            if artifact is None or artifact.session_id != session_id or artifact.tool_name != "knowledge_read":
                _hold("trusted_reads_unavailable")
            try:
                import asyncio

                result = await asyncio.to_thread(read_tool_artifact_payload, artifact)
            except (OSError, ValueError, RuntimeError) as error:
                raise SpecificationUnavailable("trusted_reads_unavailable") from error
        if (type(result) is not dict or result.get("state") != "ok"
                or result.get("evidence_key") != dict(call.parameters or {}).get("evidence_key")):
            _hold("trusted_reads_unavailable")
        shown[call.id] = _shown_keys(result)
    # Every passage a successful read showed is citable by its own key (the window's neighbours included); the
    # snapshot then freezes exactly that passage. A read's own key wins over a neighbour shown by another read.
    bound = {}
    for call in calls:
        for key in shown[call.id]:
            bound.setdefault(key, call)
    bound.update({dict(call.parameters or {}).get("evidence_key"): call for call in calls})
    return bound


def _shown_keys(result: dict) -> list[str]:
    """The keys of the passages the read result showed: its own, and its window's from the same revision."""
    own = str(result.get("evidence_key") or "")
    revision = own.rsplit(":", 1)[0]
    keys = result.get("passage_keys")
    if type(keys) is not list:
        return [own]
    if any(type(key) is not str or not is_valid_evidence_id(key) or key.rsplit(":", 1)[0] != revision
           for key in keys) or own not in keys:
        _hold("trusted_reads_unavailable")
    return keys


def take_output_provenance(db, run, kind, record, *, session_id=None, request_id=None):
    """Pre-store proof consumption: missing or mismatched authority refuses before any envelope mutation."""
    if kind != "research_brief":
        return None
    proof = db.info.get("specification_validated_reads", {}).pop(run.id, None)
    if (not proof or proof["hash"] != output_hash(record) or proof["node_id"] != run.current_node_id
            or proof["entry"] != dict(run.node_state or {}).get("entry")
            or proof["session_id"] != session_id or proof["request_id"] != request_id):
        _hold("research_provenance_unavailable")
    return proof


async def record_output_provenance(db, run, kind, *, proof=None, **_kwargs):
    """Deterministic post-store event from proof taken before storage; no I/O, checks or failure."""
    if kind == "research_brief":
        envelope = recorded_output(run, kind)
        record_event(db, run, PROVENANCE_EVENT, node_id=envelope["node_id"], detail={
            "kind": kind, "version": envelope["version"], **proof})


async def _brief_calls(db, run, brief):
    event = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id,
        WorkflowRunEvent.node_id == brief["node_id"], WorkflowRunEvent.kind == PROVENANCE_EVENT)
        .order_by(WorkflowRunEvent.created_at.desc(), WorkflowRunEvent.id.desc()).limit(1))).scalar_one_or_none()
    proof = dict(event.detail or {}) if event else {}
    if any(proof.get(key) != brief[key] for key in ("kind", "version", "hash", "entry")):
        _hold("research_provenance_unavailable")
    return await _calls(db, run, ids=proof.get("call_ids"), session_id=proof.get("session_id"),
        request_id=proof.get("request_id"), node_id=brief["node_id"], entry=brief["entry"])


async def _read(db, run, actor, key, call) -> dict:
    if call is None:
        _hold("citation_not_bound_to_research")
    span = (await db.execute(select(KnowledgeEvidenceSpan).where(
        KnowledgeEvidenceSpan.project_id == run.project_id, KnowledgeEvidenceSpan.evidence_key == key)
        .execution_options(populate_existing=True))).scalar_one_or_none()
    revision = await db.get(KnowledgeSourceRevision, span.revision_id, populate_existing=True) if span else None
    source = await db.get(KnowledgeEvidenceSource, revision.source_id, populate_existing=True) if revision else None
    if not source or source.project_id != run.project_id or revision.project_id != run.project_id:
        _hold("source_withheld_or_unavailable")
    acl = (await db.execute(select(KnowledgeSourceAcl).where(KnowledgeSourceAcl.project_id == run.project_id,
        KnowledgeSourceAcl.source_key == source.source_key).with_for_update()
        .execution_options(populate_existing=True))).scalar_one_or_none()
    principals = list((await db.execute(select(KnowledgeSourceAclPrincipal.principal_key).where(
        KnowledgeSourceAclPrincipal.project_id == run.project_id,
        KnowledgeSourceAclPrincipal.source_key == source.source_key).with_for_update())).scalars())
    head = (await db.execute(select(KnowledgeSourceHead).where(KnowledgeSourceHead.source_id == source.id)
        .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    try:
        authorized = await authorize_workspace(db, current_user=actor, workspace_id=run.project_id)
        read = await read_span_window(db, authorized=authorized, evidence_key=key, window=0)
    except EvidenceLedgerError as error:
        raise SpecificationUnavailable("source_withheld_or_unavailable") from error
    if (not read.current or not head or head.project_id != run.project_id
            or head.current_revision_id != revision.id or head.wanted_revision_id != revision.id):
        _hold("source_head_changed")
    citation = markdown_citation(read.source_title, read.source_url, ())
    if (not read.text.strip() or len(read.text) > 8000 or "\x00" in read.text or len(citation) > 2048):
        _hold("source_content_unavailable")
    return {"evidence_key": key, "call_id": call.id, "source_id": source.id, "revision_id": revision.id,
        "content_sha256": revision.content_sha256, "text": read.text, "text_hash": output_hash({"text": read.text}),
        "cite_as": citation, "retrieved_at": ensure_utc(utc_now()).isoformat(),
        "source_acl": {"workspace_id": run.project_id,
        "principal_user_id": actor.id, "acl_hash": output_hash({"restriction": acl.restriction if acl else None,
                                                               "principals": sorted(principals)})}}


async def _snapshots(db, run, actor, keys, calls, *, frozen=None):
    if not keys or len(keys) > 8:
        _hold("research_evidence_unavailable")
    result = []
    for key in keys:
        current = await _read(db, run, actor, key, calls.get(key))
        if frozen is not None:
            original = frozen.get(key)
            if (type(original) is not dict or set(original) != set(current)
                    or type(original.get("source_acl")) is not dict
                    or set(original["source_acl"]) != set(current["source_acl"])):
                _hold("research_snapshot_changed")
            try:
                timestamp = datetime.fromisoformat(original["retrieved_at"])
                if timestamp.utcoffset() is None or timestamp.utcoffset().total_seconds() != 0:
                    _hold("research_snapshot_changed")
            except (ValueError, TypeError, KeyError) as error:
                raise SpecificationUnavailable("research_snapshot_changed") from error
            for field in set(current) - {"retrieved_at", "source_acl"}:
                if original[field] != current[field]:
                    _hold("research_snapshot_changed")
            if (original["source_acl"]["principal_user_id"] != run.requested_by
                    or original["source_acl"]["workspace_id"] != run.project_id
                    or original["source_acl"]["acl_hash"] != current["source_acl"]["acl_hash"]):
                _hold("research_snapshot_changed")
            current = copy.deepcopy(original)
        result.append(current)
    if sum(len(row["text"]) for row in result) > 30000:
        _hold("research_evidence_exceeds_bound")
    return result


async def _budget_still_bound(db, run, recorded: dict) -> bool:
    """The confirmed plan's budget, or a raise of it that a recorded budget-limit continue made after the confirm.

    A budget only changes at run start or through that supported continue (``pause.continue_run``), which records
    the new budget. Raising the budget does not change research already done, so it keeps the lineage; a lowered
    or otherwise differing budget, or one without that recorded decision, does not."""
    effective = effective_budget(run)
    if effective == recorded:
        return True
    if set(effective) != set(recorded) or any(effective[key] < recorded[key] for key in recorded):
        return False
    plan_decision = await db.get(WorkflowRunDecision, (await _confirmed(db, run, "research_plan"))["decision_id"])
    raised = (await db.execute(select(WorkflowRunDecision).where(
        WorkflowRunDecision.run_id == run.id, WorkflowRunDecision.kind == "pause",
        WorkflowRunDecision.subject == "budget_limit", WorkflowRunDecision.action == "continue")
        .order_by(WorkflowRunDecision.created_at.desc(), WorkflowRunDecision.id.desc()).limit(1))).scalar_one_or_none()
    return (plan_decision is not None and raised is not None and plan_decision.created_at is not None
            and raised.created_at is not None and ensure_utc(raised.created_at) >= ensure_utc(plan_decision.created_at)
            and dict(raised.payload or {}).get("budget") == effective)


async def _plan(db, run):
    envelope = await _envelope(db, run, "research_plan")
    if envelope["record"]["idea_frame_ref"] != await _confirmed(db, run, "idea_frame"):
        _hold("idea_confirmation_changed")
    if not await _budget_still_bound(db, run, envelope["record"]["budget"]):
        _hold("research_budget_changed")
    return envelope


async def _brief(db, run, actor):
    envelope = await _envelope(db, run, "research_brief")
    await _plan(db, run)
    if envelope["record"]["research_plan_ref"] != await _confirmed(db, run, "research_plan"):
        _hold("research_plan_confirmation_changed")
    calls = await _brief_calls(db, run, envelope)
    rows = envelope["record"].get("evidence")
    keys = used_keys(envelope["record"])
    if type(rows) is not list or len(rows) != len(keys):
        _hold("research_snapshot_changed")
    frozen = {row.get("evidence_key"): row for row in rows if type(row) is dict}
    evidence = await _snapshots(db, run, actor, keys, calls, frozen=frozen)
    return envelope, evidence, calls


async def canonicalize_output(db, run, kind, proposal, *, principal, session_id=None,
                              request_id=None, tool_history=None) -> dict:
    """Enrich an already phase-authorized proposal; refusal never mutates the Run or existing output."""
    if kind == "research_brief":
        db.info.get("specification_validated_reads", {}).pop(run.id, None)
    record, errors = validate_proposal(kind, proposal)
    if errors:
        _hold("proposal_invalid", invalid=True)
    actor = await _actor(db, run, principal)
    if actor.id != run.requested_by:
        _hold("producer_principal_changed")
    if kind == "research_plan":
        record.update(idea_frame_ref=await _confirmed(db, run, "idea_frame"), budget=effective_budget(run))
    elif kind == "research_brief":
        await _plan(db, run)
        record["research_plan_ref"] = await _confirmed(db, run, "research_plan")
        calls = await _calls(db, run, ids=_trusted_ids(tool_history), session_id=session_id,
            request_id=request_id, node_id=run.current_node_id, entry=dict(run.node_state or {}).get("entry"))
        record["evidence"] = await _snapshots(db, run, actor, used_keys(record), calls)
    elif kind == "spec":
        brief, evidence, _ = await _brief(db, run, actor)
        keys = used_keys(record)
        if not set(keys) <= {row["evidence_key"] for row in evidence}:
            _hold("spec_citation_not_in_brief", invalid=True)
        record.update(idea_frame_ref=await _confirmed(db, run, "idea_frame"), research_brief_ref=_ref(run, brief),
                      evidence=[row for row in evidence if row["evidence_key"] in keys])
    if len(json.dumps(record, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 262144:
        _hold("canonical_record_exceeds_bound", invalid=True)
    if kind == "research_brief":
        db.info.setdefault("specification_validated_reads", {})[run.id] = {
            "hash": output_hash(record), "node_id": run.current_node_id,
            "entry": dict(run.node_state or {}).get("entry"), "session_id": session_id,
            "request_id": request_id, "call_ids": sorted(row["call_id"] for row in record["evidence"])}
    return record


async def resolve_spec_snapshot(db, run, *, principal, purpose="review", kind="spec") -> dict:
    """Actual viewer/confirmer/read-only reviewer recheck. Review pass is checked separately by Root."""
    if kind not in KINDS or purpose not in {"review", "preview", "confirm"}:
        _hold("resolver_contract_invalid", invalid=True)
    actor = await _actor(db, run, principal)
    envelope = await _envelope(db, run, kind)
    evidence = []
    upstream = {}
    if kind == "research_plan":
        await _plan(db, run)
    elif kind in {"research_brief", "spec"}:
        brief, admitted, calls = await _brief(db, run, actor)
        evidence = admitted
        if kind == "spec":
            record = envelope["record"]
            if (record["idea_frame_ref"] != await _confirmed(db, run, "idea_frame")
                    or record["research_brief_ref"] != _ref(run, brief)):
                _hold("upstream_artefact_changed")
            rows = record["evidence"]
            keys = used_keys(record)
            if type(rows) is not list or len(rows) != len(keys) or not set(keys) <= set(used_keys(brief["record"])):
                _hold("research_snapshot_changed")
            frozen = {row.get("evidence_key"): row for row in rows if type(row) is dict}
            brief_by_key = {row["evidence_key"]: row for row in admitted}
            if any(frozen.get(key) != brief_by_key.get(key) for key in keys):
                _hold("research_snapshot_changed")
            evidence = await _snapshots(db, run, actor, keys, calls, frozen=frozen)
            upstream = {"idea_frame": copy.deepcopy(await _envelope(db, run, "idea_frame")),
                        "research_brief": copy.deepcopy(brief)}
    binding = {**_ref(run, envelope), "principal_user_id": actor.id, "workspace_id": run.project_id}
    binding.update({key: copy.deepcopy(value) for key, value in envelope["record"].items() if key.endswith("_ref")})
    return {"envelope": copy.deepcopy(envelope), "evidence": evidence, "binding": binding, "upstream": upstream}
