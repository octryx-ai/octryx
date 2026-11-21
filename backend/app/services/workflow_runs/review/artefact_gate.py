"""A distinct artifact gate: no invented Git tree or has_change flag."""
from __future__ import annotations

from sqlalchemy import select

from ....models import WorkflowRunEvent
from ..phase_outputs import output_hash
from .artefact_contract import SNAPSHOT_EVENT, ArtefactUnavailableError, parse_verdict
from .artefact_evidence import resolve_snapshot


def evaluate(record):
    if not record or record.get("mode") != "artefact" or record.get("binding_verified") is not True:
        return "failed", "no current independent artifact review"
    verdict = parse_verdict({key: record.get(key) for key in ("verdict", "summary", "findings")})
    if verdict is None:
        return "failed", "invalid artifact verdict"
    return ("passed", "") if verdict.passed else ("failed", "; ".join(f.render() for f in verdict.findings))


async def gate_record(db, run, gate):
    from ...knowledge.ledger.errors import EvidenceLedgerError
    from ..graph import graph_for_run
    from ..records import WorkflowRunError

    record = dict(dict(run.context or {}).get("review") or {})
    graph = await graph_for_run(db, run)
    node = graph.nodes.get(record.get("node_id"))
    if (node is None or node.kind != "review" or node.config.get("mode") != "artefact"
            or record.get("mode") != "artefact" or not record.get("attempt")
            or not any(e.source == node.id and e.target == gate.id for e in graph.edges)):
        return None
    snapshot_event = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.node_id == node.id,
        WorkflowRunEvent.kind == SNAPSHOT_EVENT).order_by(WorkflowRunEvent.created_at.desc(),
        WorkflowRunEvent.id.desc()).limit(1))).scalar_one_or_none()
    detail = dict(snapshot_event.detail or {}) if snapshot_event else {}
    events = select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.node_id == node.id)
    entered = (await db.execute(events.where(WorkflowRunEvent.kind == "node_entered")
        .order_by(WorkflowRunEvent.created_at.desc(), WorkflowRunEvent.id.desc()).limit(1))).scalar_one_or_none()
    verdict_event = (await db.execute(events.where(WorkflowRunEvent.kind == "review_verdict")
        .order_by(WorkflowRunEvent.created_at.desc(), WorkflowRunEvent.id.desc()).limit(1))).scalar_one_or_none()
    if (detail.get("attempt") != record["attempt"] or detail.get("snapshot_hash") != record.get("snapshot_hash")
            or entered is None
            or dict(entered.detail or {}).get("entry") != record.get("binding", {}).get("review_entry")
            or verdict_event is None or dict(verdict_event.detail or {}).get("attempt") != record["attempt"]):
        return None
    # Review pass number is frozen in the snapshot; gate has its own cursor. Resolve against the review cursor.
    try:
        current = await resolve_snapshot(db, run, node,
            review_entry=dict(record.get("binding") or {}).get("review_entry"))
    except (ArtefactUnavailableError, EvidenceLedgerError, WorkflowRunError):
        return None
    if (output_hash(current) != detail.get("snapshot_hash")
            or output_hash(detail.get("snapshot") or {}) != record.get("snapshot_hash")):
        return None
    return {**record, "binding_verified": True}
