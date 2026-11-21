"""Scoring of one case: availability, hit resolution, precision, coverage, outcome and acceptance."""

from __future__ import annotations

from typing import Any

from .library_inputs import Case, Manifest
from .library_inventory import EvidenceInventory
from .library_judgments import (
    _excluded,
    _identities,
    _ratio,
)

# The hybrid contract (retrieval/hybrid.py, retrieval/scoped.py): an answering Workspace reports exactly these
# components; a Workspace that did not answer reports one whole-Workspace {"state": ...} entry instead.
HYBRID_COMPONENTS = frozenset({"lexical", "vector", "rerank"})
# Whole-Workspace states that are a deliberate scope decision, not a failed retrieval.
NOT_APPLICABLE_STATES = frozenset({"outside_binding_products", "classification_above_reader"})
# Skipped because the binding's classification could not be resolved: not a failure of retrieval, but nothing
# shows the Workspace was meant to be out of scope, so the result is not complete.
UNRESOLVED_SKIP_STATES = frozenset({"classification_unresolved"})


def _hybrid_entry(states: Any) -> tuple[str, Any] | None:
    """``("answered", components)``, ``("whole", state)`` or ``None`` when it fits neither contract shape."""
    if not isinstance(states, dict) or not all(isinstance(value, str) for value in states.values()):
        return None
    if set(states) == HYBRID_COMPONENTS:
        return "answered", states
    if set(states) == {"state"}:
        return "whole", states["state"]
    return None


def classify_availability(record: dict[str, Any], case: Case) -> dict[str, Any]:
    """complete / partial / error / malformed against the actual response contract, keeping the raw states."""
    raw = {"mode_states": record.get("mode_states"), "workspace_states": record.get("workspace_states")}
    if record.get("response_state") != "ok":
        return {"class": "error", "raw": raw}
    modes = record.get("mode_states")
    if not record.get("metadata_valid") or not isinstance(modes, dict):
        return {"class": "malformed", "raw": raw}
    if case.mode != "hybrid":
        # The route reports a constant {mode: "ok"} for lexical and vector; a failure is an HTTP error instead.
        if modes != {case.mode: "ok"}:
            return {"class": "malformed", "raw": raw}
        return {"class": "complete", "ok": 1, "not_applicable": 0, "unresolved": 0, "failed": 0, "raw": raw,
                "api_reported_constant": True}
    workspaces = record.get("workspace_states")
    entries = [_hybrid_entry(states) for states in workspaces.values()] if isinstance(workspaces, dict) else []
    # mode_states is the reader's own entry of workspace_states; it must match one of them exactly.
    if not entries or None in entries or _hybrid_entry(modes) is None or modes not in list(workspaces.values()):
        return {"class": "malformed", "raw": raw}
    counts = dict.fromkeys(("ok", "not_applicable", "unresolved", "failed"), 0)
    for shape, value in entries:
        if shape == "answered":
            for state in value.values():
                counts["ok" if state == "ok" else "failed"] += 1
        elif value in NOT_APPLICABLE_STATES:
            counts["not_applicable"] += 1
        elif value in UNRESOLVED_SKIP_STATES:
            counts["unresolved"] += 1
        else:
            counts["failed"] += 1
    klass = "error" if counts["ok"] == 0 else ("partial" if counts["failed"] or counts["unresolved"] else "complete")
    return {"class": klass, **counts, "raw": raw, "api_reported_constant": False}


def _corpus_verification(case: Case, inventory: EvidenceInventory | None) -> dict[str, str]:
    corpus = {
        fact.id: ([inventory.verify(ref) for ref in fact.evidence] if inventory else ["unverified"])
        for fact in case.facts if fact.required
    }
    return {
        fact_id: "verified" if "verified" in states else ("stale" if "stale" in states else states[0])
        for fact_id, states in corpus.items()
    }


def _resolve_groups(
    groups: list[list[dict[str, Any]]], case: Case, judged: dict[str, dict[str, Any]], manifest: Manifest
) -> dict[str, Any]:
    """One resolution per identity: every count, coverage and rank of the case uses this same label."""
    counts = dict.fromkeys(("relevant", "partial", "irrelevant", "excluded_leak", "unjudged"), 0)
    full_prelabeled: set[str] = set()
    full_judged: set[str] = set()
    partial: set[str] = set()
    leaks: list[str] = []
    unverifiable = False
    relevant_ranks: list[int] = []
    for group in groups:
        hit = group[0]
        exclusion = [_excluded(item, case, manifest) for item in group]
        if True in exclusion:
            counts["excluded_leak"] += 1
            leaks.append(hit["evidence_key"])
            continue
        unverifiable |= None in exclusion
        prelabeled = {
            fact.id for fact in case.facts for item in group if any(ref.matches(item) for ref in fact.evidence)
        }
        judgment = next((judged[item["evidence_key"]] for item in group if item["evidence_key"] in judged), None)
        label = "relevant" if prelabeled else (judgment["label"] if judgment else "unjudged")
        counts[label] += 1
        if label == "relevant":
            relevant_ranks.append(min(item["rank"] for item in group))
            full_prelabeled |= prelabeled
            full_judged |= prelabeled | set(judgment["supports"] if judgment else ())
        elif label == "partial":
            partial |= set(judgment["supports"])
    return {"counts": counts, "full_prelabeled": full_prelabeled, "full_judged": full_judged, "partial": partial,
            "leaks": leaks, "unverifiable": unverifiable, "relevant_ranks": relevant_ranks}


def _fact_coverage(required: list[str], resolved: dict[str, Any]) -> dict[str, Any]:
    partial = resolved["partial"]
    return {
        view: {
            "covered": sorted(set(required) & covered),
            "partially_covered": sorted((set(required) & partial) - covered) if view == "judged" else [],
            "missing": sorted(set(required) - covered - (partial if view == "judged" else set())),
            "ratio": _ratio(len(set(required) & covered), len(required), "required_facts"),
        }
        for view, covered in (("prelabeled", resolved["full_prelabeled"]), ("judged", resolved["full_judged"]))
    }


def _case_outcome(
    case: Case, availability: dict[str, Any], unique: int, required: list[str], resolved: dict[str, Any]
) -> str:
    leaks, unverifiable = resolved["leaks"], resolved["unverifiable"]
    if case.kind == "answer":
        outcome = "complete" if set(required) <= resolved["full_judged"] else "incomplete"
    elif case.kind == "no_answer":
        if unique:
            outcome = f"false_positive:{unique}"
        else:
            outcome = "true_empty" if availability["class"] == "complete" else "empty_degraded"
    else:
        outcome = "leak" if leaks else ("unverifiable" if unverifiable else "no_leak")
    if leaks and case.kind != "exclusion":
        outcome += "+leak"
    return outcome


def _score_case(
    case: Case, record: dict[str, Any], judged: dict[str, dict[str, Any]], manifest: Manifest,
    inventory: EvidenceInventory | None,
) -> dict[str, Any]:
    availability = classify_availability(record, case)
    result: dict[str, Any] = {
        "case_id": case.id, "split": case.split, "kind": case.kind, "mode": case.mode, "scope": case.scope,
        "response_state": record["response_state"], "error_code": record.get("error_code"),
        "latency_ms": record["latency_ms"], "availability": availability,
    }
    result["corpus_verification"] = _corpus_verification(case, inventory)
    if record["response_state"] != "ok":
        result["outcome"] = "error"
        result["acceptance"] = _acceptance(case, result, unjudged=0)
        return result

    groups = _identities(record["hits"])
    resolved = _resolve_groups(groups, case, judged, manifest)
    counts, leaks, relevant_ranks = resolved["counts"], resolved["leaks"], resolved["relevant_ranks"]
    unique, raw_returned = len(groups), len(record["hits"])
    judged_total = unique - counts["unjudged"]
    result["hits"] = {"raw_returned": raw_returned, "unique": unique, "duplicates": raw_returned - unique, **counts}
    result["precision_strict"] = _ratio(counts["relevant"], judged_total, "judged_unique_hits")
    result["precision_lenient"] = _ratio(counts["relevant"] + counts["partial"], judged_total, "judged_unique_hits")
    result["precision_strict_bounds"] = [
        _ratio(counts["relevant"], unique, "unique_hits"),
        _ratio(counts["relevant"] + counts["unjudged"], unique, "unique_hits"),
    ]
    result["first_relevant_rank"] = min(relevant_ranks) if relevant_ranks else None
    required = [fact.id for fact in case.facts if fact.required]
    result["fact_coverage"] = _fact_coverage(required, resolved)
    result["leaks"] = leaks
    # Every case kind reports whether its exclusions could be checked; an unknown is never a pass.
    if not case.exclusions:
        result["exclusion_check"] = "not_requested"
    else:
        result["exclusion_check"] = "leak" if leaks else ("unverifiable" if resolved["unverifiable"] else "verified")
    result["outcome"] = _case_outcome(case, availability, unique, required, resolved)
    result["acceptance"] = _acceptance(case, result, unjudged=counts["unjudged"])
    return result


def _acceptance(case: Case, result: dict[str, Any], *, unjudged: int) -> dict[str, Any]:
    if case.split != "holdout":
        return {"state": "not_applicable", "reasons": [f"split {case.split}"]}
    reasons = []
    if result["response_state"] != "ok":
        reasons.append("response_not_ok")
        if case.exclusions:
            reasons.append("exclusion_not_evaluated")
    if result["availability"]["class"] != "complete":
        reasons.append(f"availability_{result['availability']['class']}")
    for fact_id, state in result["corpus_verification"].items():
        if state != "verified":
            reasons.append(f"evidence_{state}:{fact_id}")
    if unjudged:
        reasons.append(f"unjudged_hits:{unjudged}")
    if result.get("exclusion_check") == "unverifiable":
        reasons.append("exclusion_unverifiable")
    return {"state": "refused" if reasons else "eligible", "reasons": reasons}
