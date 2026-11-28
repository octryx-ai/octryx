"""Current-principal projections and submit integration for the additive spec-handoff records."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

KINDS = frozenset({"idea_frame", "research_plan", "research_brief", "spec"})


def proposal_validator(kind: str):
    def validate(raw):
        from .records import validate_proposal

        return validate_proposal(kind, raw)

    return validate


async def actual_principal(db, run, principal):
    from ....models import User

    # Internal phase entry has no viewer. External callers always pass their actual authenticated User.
    return principal if principal is not None else await db.get(User, run.requested_by)


async def _accepted_input(db, run, kind: str) -> bool:
    from ..data_flow import receives_spec
    from ..graph import graph_for_run

    return kind == "spec" and receives_spec(await graph_for_run(db, run))


async def _accepted_principal(db, run, principal):
    from ....models import User

    return principal if principal is not None else await db.get(User, run.requested_by)


def _coverage(run, criteria: list[dict[str, Any]], envelope: dict[str, Any]) -> tuple[list[dict], list[str]]:
    from ..phase_outputs import recorded_output

    contract = dict((recorded_output(run, "test_contract") or {}).get("record") or {})
    source = dict(contract.get("criteria_source") or {})
    by_id = {str(item.get("id")): item for item in contract.get("criteria") or [] if isinstance(item, dict)}
    rows, blockers = [], []
    if contract and (source.get("kind") != "spec" or source.get("hash") != envelope["hash"]
                     or source.get("version") != envelope["version"]):
        blockers.append("The recorded test contract was not checked against this accepted specification version.")
    for criterion in criteria:
        entry = by_id.get(criterion["id"])
        roles = dict((entry or {}).get("test_roles") or {})
        new = [test for test in (entry or {}).get("tests") or [] if roles.get(test) == "new"]
        manual = str((entry or {}).get("manual_reason") or "").strip() if (entry or {}).get("manual_only") else ""
        rows.append({"id": criterion["id"], "given": criterion["given"], "when": criterion["when"],
                     "then": criterion["then"], "new_tests": new, "manual_reason": manual or None,
                     "covered": bool(new or manual)})
        if not (new or manual):
            blockers.append(f"{criterion['id']}: the recorded test contract has no genuine new test or manual reason "
                            "for this accepted criterion.")
    return rows, blockers


async def _accepted_shown(db, run, *, principal) -> dict[str, Any]:
    from .origin import viewer_spec

    snapshot = await viewer_spec(db, run, await _accepted_principal(db, run, principal))
    envelope = snapshot["envelope"]
    record = deepcopy(envelope["record"])
    coverage, blockers = _coverage(run, record.get("criteria") or [], envelope)
    binding = snapshot["binding"]
    return {"output": {"version": envelope["version"], "hash": envelope["hash"], **record},
            "accepted_spec": {"parent_run_id": binding["parent_run_id"], "version": envelope["version"],
                              "hash": envelope["hash"], **deepcopy(snapshot["confirmation"])},
            "coverage": coverage, **({"blockers": blockers} if blockers else {})}


async def shown_output(db, run, *, kind: str, principal=None, purpose="preview") -> dict[str, Any]:
    from .lineage import SpecificationUnavailable, resolve_spec_snapshot

    if await _accepted_input(db, run, kind):
        return dict((await _accepted_shown(db, run, principal=principal))["output"])

    snapshot = await resolve_spec_snapshot(
        db, run, principal=await actual_principal(db, run, principal), purpose=purpose, kind=kind)
    envelope = snapshot["envelope"]
    record = deepcopy(envelope["record"])
    if kind == "spec" and purpose == "confirm":
        review = dict(dict(run.context or {}).get("review") or {})
        binding = dict(review.get("binding") or {})
        if (review.get("mode") != "artefact" or review.get("verdict") != "pass"
                or binding.get("kind") != kind or binding.get("hash") != envelope["hash"]
                or binding.get("version") != envelope["version"]):
            raise SpecificationUnavailable("spec_review_missing_or_changed")
    return {"version": envelope["version"], "hash": envelope["hash"], **record}


async def shown_payload(db, run, *, kind, principal=None, purpose="preview") -> dict[str, Any]:
    from .lineage import SpecificationUnavailable

    if await _accepted_input(db, run, kind):
        try:
            return await _accepted_shown(db, run, principal=principal)
        except SpecificationUnavailable:
            return {"output": None, "missing": "The accepted specification is unavailable or your current access to "
                                               "its sources could not be verified."}
    try:
        shown = await shown_output(db, run, kind=kind, principal=principal, purpose=purpose)
    except SpecificationUnavailable:
        return {"output": None,
                "missing": "The current specification record is unavailable or its source access changed."}
    blockers = []
    if shown.get("open_questions"):
        blockers.append("Resolve the open questions or explicitly defer them with a reason before confirming.")
    return {"output": shown, **({"blockers": blockers} if blockers else {})}


def _withhold(waiting: dict, payload: dict) -> None:
    waiting["payload"] = {"subject": payload.get("subject"), "shows": payload.get("shows"),
                          "missing": "The record is withheld until source access and bindings are verified."}
    waiting["payload_hash"] = None


async def protected_waiting(db, run) -> bool:
    from .origin import spec_bound

    payload = dict(dict(dict(run.node_state or {}).get("waiting") or {}).get("payload") or {})
    return bool(payload) and (payload.get("shows") in KINDS or await spec_bound(db, run))


async def projected_node_state(db, run, *, principal) -> dict[str, Any]:
    # Run membership alone never discloses source-bearing payloads after ACL or head drift.
    from .lineage import SpecificationUnavailable
    from .origin import spec_bound, viewer_spec

    state = deepcopy(dict(run.node_state or {}))
    waiting = state.get("waiting")
    if not isinstance(waiting, dict):
        return state
    payload = waiting.get("payload")
    if not isinstance(payload, dict):
        return state
    if await spec_bound(db, run):
        # Every card of a spec-bound run carries accepted-spec content: the viewer's OWN authority, then the shown.
        try:
            await viewer_spec(db, run, principal)
        except SpecificationUnavailable:
            _withhold(waiting, payload)
            return state
    if payload.get("shows") not in KINDS:
        return state
    projected = (await shown_payload(db, run, kind=payload["shows"], principal=principal)
                 if principal is not None else {"output": None})
    previous = payload.get("output")
    current = projected.get("output")
    if (principal is None or current is None or not isinstance(previous, dict)
            or current.get("hash") != previous.get("hash") or current.get("version") != previous.get("version")):
        _withhold(waiting, payload)
    return state


async def authorized_phase_definition(db, run, node, *, principal):
    from ..phase_contract import phase_definition
    from ..phase_marker import RUN_PHASE_CONTRACT_KEY
    from ..phase_outputs import phase_inputs
    from .lineage import resolve_spec_snapshot
    from .origin import spec_bound, viewer_spec

    definition = phase_definition(run, node)
    facts = definition["workflow_contract"][RUN_PHASE_CONTRACT_KEY]
    inputs = dict(facts.get("inputs") or {})
    accepted = None
    if await spec_bound(db, run):
        # The actual caller's own authority, even for a phase whose test contract only quotes the spec's criteria.
        accepted = await viewer_spec(db, run, principal)
    for kind in phase_inputs(node):
        if kind in KINDS and accepted is not None and await _accepted_input(db, run, kind):
            inputs[kind] = deepcopy(accepted["envelope"]["record"])
        elif kind in KINDS:
            snapshot = await resolve_spec_snapshot(
                db, run, principal=await actual_principal(db, run, principal), purpose="preview", kind=kind)
            inputs[kind] = deepcopy(snapshot["envelope"]["record"])
    review = dict(dict(run.context or {}).get("review") or {})
    if (facts.get("review_findings") and review.get("mode") == "artefact"
            and dict(review.get("binding") or {}).get("kind") == "spec" and "research_brief" not in inputs):
        # Even a custom phase without declared inputs may carry a review's quoted source facts.
        await resolve_spec_snapshot(db, run, principal=await actual_principal(db, run, principal),
                                    purpose="preview", kind="research_brief")
    if inputs:
        facts["inputs"] = inputs
    return definition


def source_phase(node) -> bool:
    from ..phase_outputs import phase_inputs, phase_output

    return phase_output(node) in KINDS or bool(KINDS.intersection(phase_inputs(node)))


async def source_backed_phase(db, run, node) -> bool:
    from .origin import spec_bound

    return source_phase(node) or await spec_bound(db, run)


async def projected_phase_facts(db, run, node, *, principal) -> dict:
    from ..phase_marker import RUN_PHASE_CONTRACT_KEY
    from .lineage import SpecificationUnavailable

    if principal is not None:
        try:
            definition = await authorized_phase_definition(db, run, node, principal=principal)
            facts = definition["workflow_contract"][RUN_PHASE_CONTRACT_KEY]
            return {key: deepcopy(facts.get(key, {} if key == "inputs" else []))
                    for key in ("inputs", "findings", "review_findings")}
        except SpecificationUnavailable:
            pass
    return {"inputs": {}, "findings": [], "review_findings": [], "source_status": "needs_configuration"}


async def readiness_states(db, run, checks) -> dict:
    from ..phase_outputs import recorded_output
    from .lineage import SpecificationUnavailable, resolve_spec_snapshot
    from .records import record_readiness

    states = {}
    for check in checks:
        if check.get("type") != "specification_ready":
            continue
        kind = dict(check.get("params") or {}).get("kind")
        if type(kind) is not str:
            continue
        if kind not in KINDS or recorded_output(run, kind) is None:
            states[kind] = {"state": "failed", "reason": "No current specification record was submitted."}
            continue
        try:
            snapshot = await resolve_spec_snapshot(
                db, run, principal=await actual_principal(db, run, None), purpose="preview", kind=kind)
        except SpecificationUnavailable:
            states[kind] = {"state": "needs_configuration", "reason": "The source bindings are unavailable."}
            continue
        ready, detail = record_readiness(kind, snapshot["envelope"]["record"])
        states[kind] = {"state": "passed" if ready else "failed", "reason": detail}
    return states
