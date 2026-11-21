"""Artifact worker adapter, preserving the existing attempt claim and governed model dispatch."""
from __future__ import annotations

from ...knowledge.ledger.errors import EvidenceLedgerError
from ..phase_outputs import output_hash
from ..records import WorkflowRunError, record_event
from .artefact_contract import (
    SNAPSHOT_EVENT,
    ArtefactUnavailableError,
    answer_contract,
    parse_verdict,
    verdict_rejection,
)
from .artefact_evidence import resolve_snapshot, task_for
from .model import ReviewModelUnavailableError
from .reviewer_agent import reviewer_setup


async def ask(db, run, node, model_factory):
    try:
        snapshot = await resolve_snapshot(db, run, node)
    except (ArtefactUnavailableError, EvidenceLedgerError, WorkflowRunError) as error:
        reason = str(error) if isinstance(error, ArtefactUnavailableError) else "owner_or_source_unavailable"
        return None, None, f"needs_configuration:{reason}", "", {}
    setup = await reviewer_setup(db, run)
    if isinstance(setup, str):
        return None, None, setup, "", {}
    digest = output_hash(snapshot)
    record_event(db, run, SNAPSHOT_EVENT, node_id=node.id, detail={
        "attempt": dict(run.node_state["waiting"])["attempt"], "snapshot_hash": digest, "snapshot": snapshot})
    await db.commit()  # Snapshot and claim are durable before any model I/O.
    facts = {"mode": "artefact", "binding": snapshot["binding"], "snapshot_hash": digest,
        "reviewer_agent": setup.definition_id, "reviewer_revision_id": setup.revision_id,
        "reviewer_revision_number": setup.revision_number, "reviewer_checksum": setup.checksum,
        "_snapshot": snapshot}
    from .call_inputs import _review_model
    from .choice import review_choice

    choice = await review_choice(db, run, dict(node.config or {}))
    if isinstance(choice, str):
        return None, None, choice, "", facts
    facts.update(choice.facts())
    try:
        model = await _review_model(model_factory, db, run, setup, choice)
        answered = await model.answer(system=f"{setup.instructions}\n{answer_contract(snapshot['binding']['kind'])}",
                                      user=task_for(snapshot))
    except ReviewModelUnavailableError as error:
        return None, None, error.reason, "", facts
    verdict = parse_verdict(answered.answer)
    usage = answered.usage
    facts.update(reviewer_runtime_shared=bool(getattr(model, "runtime_shared", False)),
                 serving_model=getattr(usage, "model", None), serving_provider=getattr(usage, "provider", None))
    reason = "" if verdict else f"invalid_artefact_verdict:{verdict_rejection(answered.answer)}"
    return verdict, usage, reason, "", facts


async def still_current(db, run, snapshot: dict) -> bool:
    from ..graph import graph_for_run

    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id)
    if node is None:
        return False
    try:
        current = await resolve_snapshot(db, run, node)
    except (ArtefactUnavailableError, EvidenceLedgerError, WorkflowRunError):
        return False
    return output_hash(current) == output_hash(snapshot)
