"""Offline scoring of a Library evaluation capture against its frozen manifest.

Pure: no network, no database. Every input is re-validated and re-hashed from its content; any problem
returns ``status: "invalid"`` with reasons and no scores. Semantics:

* Hits are deduplicated into identities (same evidence key, or same source/revision hash/span). Raw,
  unique and duplicate counts are reported; all precision figures use unique identities.
* A hit matching a manifest alternative is ``relevant`` (prelabeled) for that fact; a hit matching an
  exclusion is an ``excluded_leak`` and cannot be judged otherwise. Everything else needs an independent
  judgment (``relevant``, ``partial``, ``irrelevant``) or stays ``unjudged``: never correct, never false.
* Strict precision = relevant / judged unique hits; lenient adds partial; the bounds over all unique hits
  show what the unjudged hits could change. Each ratio carries its numerator and denominator.
* Fact coverage is reported twice: prelabeled alternatives only, and including judged equivalent evidence.
  Partial support never counts as covered. Duplicates never add coverage.
* An error, malformed or degraded response is never a true empty answer.
* Holdout acceptance additionally needs a capture after the freeze, verified corpus evidence for every
  required fact, complete availability and no unjudged hit. Declarations (principal, environment) stay
  declarations: nothing here verifies them.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .library_case_scores import _score_case
from .library_inputs import EvaluationInputError, Manifest, canonical_sha256
from .library_inventory import load_inventory
from .library_judgments import _ratio, _validate_judgments
from .library_records import validate_capture

REPORT_SCHEMA = "octryx.library_eval.report/v1"
LIMITS = (
    "Ranks, similarity and relevance are uncalibrated; no score is a calibrated probability.",
    "lexical and vector search only the own Workspace; only hybrid measures Library scope.",
    "Principal role and environment are operator declarations, not verified here.",
    "Provider usage is not exposed by the search API and stays unavailable; the logical estimate is not billing.",
    "Normalized query equality detects known reuse only; it does not certify a pristine holdout.",
    "A captured excerpt is not proof that unretrieved required evidence existed; only the inventory is.",
)


def _percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(round(share * len(ordered) + 0.5)) - 1))]


def _aggregate(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        groups[(result["split"], result["mode"], result["scope"], result["availability"]["class"])].append(result)
    rows = []
    for (split, mode, scope, availability), items in sorted(groups.items()):
        scored = [item for item in items if "hits" in item]
        total = defaultdict(int)
        for item in scored:
            for key, value in item["hits"].items():
                total[key] += value
        judged = total["unique"] - total["unjudged"]
        required = sum(item["fact_coverage"]["judged"]["ratio"]["denominator"] for item in scored)
        covered = sum(item["fact_coverage"]["judged"]["ratio"]["numerator"] for item in scored)
        latencies = [item["latency_ms"] for item in items]
        outcomes: dict[str, int] = defaultdict(int)
        for item in items:
            outcomes[item["outcome"].split(":")[0]] += 1
        rows.append({
            "split": split, "mode": mode, "scope": scope, "availability": availability,
            "cases": len(items), "errors": len(items) - len(scored), "hits": dict(total),
            "precision_strict": _ratio(total["relevant"], judged, "judged_unique_hits"),
            "precision_lenient": _ratio(total["relevant"] + total["partial"], judged, "judged_unique_hits"),
            "fact_coverage_judged": _ratio(covered, required, "required_facts"),
            "outcomes": dict(outcomes),
            "latency_ms": {
                "n": len(latencies), "p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)
            },
        })
    return rows


def _safe_sha(document: Any, name: str, problems: list[str]) -> str:
    """The canonical hash; non-finite numbers or non-JSON content make the input invalid."""
    if not isinstance(document, dict):
        problems.append(f"{name}: must be a JSON object")
        return ""
    try:
        return canonical_sha256(document)
    except (TypeError, ValueError):
        problems.append(f"{name}: contains non-finite numbers or non-JSON values")
        return ""


def score_documents(
    manifest: Manifest, capture: Any, judgments: Any = None, inventory_document: Any = None
) -> dict[str, Any]:
    """Validate every input, then score; any problem yields an invalid report without scores."""
    problems: list[str] = []
    capture_sha = _safe_sha(capture, "capture", problems)
    judgments_sha = _safe_sha(judgments, "judgments", problems) if judgments is not None else None
    records = validate_capture(capture, manifest, problems) if not problems else {}
    judged = _validate_judgments(judgments, manifest, capture_sha, records, problems) if not problems else {}
    inventory = None
    if inventory_document is not None:
        try:
            inventory = load_inventory(inventory_document)
        except EvaluationInputError as error:
            problems.extend(error.problems)
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "inputs": {
            "manifest_sha256": manifest.sha256,
            "capture_sha256": capture_sha or None,
            "judgments_sha256": judgments_sha,
            "judge": judgments.get("judge") if isinstance(judgments, dict) else None,
            "inventory_sha256": inventory.sha256 if inventory else None,
        },
        "declarations": {
            "principal": manifest.raw.get("principal"),
            "environment": manifest.raw.get("environment_declared"),
            "verified": False,
        },
        "overlap_check": manifest.overlap_check,
        "logical_provider_estimate": manifest.logical_provider_estimate,
        "provider_usage": {"state": "unavailable", "reason": "not_exposed_by_search_api"},
        "limits": list(LIMITS),
    }
    if problems:
        return {**report, "status": "invalid", "problems": problems}
    results = [
        _score_case(case, records[case.id], judged.get(case.id, {}), manifest, inventory) for case in manifest.cases
    ]
    return {**report, "status": "scored", "cases": results, "aggregates": _aggregate(results)}


__all__ = ["REPORT_SCHEMA", "score_documents"]
