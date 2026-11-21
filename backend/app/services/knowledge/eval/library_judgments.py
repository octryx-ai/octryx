"""Independent judgments of captured hits: identities, exclusion leaks and judgment validation."""

from __future__ import annotations

from typing import Any

from .library_inputs import MODE_SCOPE, Case, Manifest

JUDGMENTS_SCHEMA = "octryx.library_eval.judgments/v1"
LABELS = ("relevant", "partial", "irrelevant")


def _ratio(numerator: int, denominator: int, population: str) -> dict[str, Any]:
    value = round(numerator / denominator, 4) if denominator else None
    return {"numerator": numerator, "denominator": denominator, "population": population, "value": value}


def _span(hit: dict[str, Any]) -> tuple[Any, Any, Any]:
    return hit.get("source_id"), hit.get("content_sha256"), hit.get("span_ordinal")


def _identities(hits: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group hits that name the same evidence: same key, or same source, revision hash and span."""
    groups: list[list[dict[str, Any]]] = []
    for hit in hits:
        span = _span(hit)
        complete_span = all(part is not None for part in span)
        for group in groups:
            if any(
                other["evidence_key"] == hit["evidence_key"]
                or (complete_span and _span(other) == span)
                for other in group
            ):
                group.append(hit)
                break
        else:
            groups.append([hit])
    return groups


def _validate_judgments(
    judgments: Any, manifest: Manifest, capture_sha: str, records: dict[str, dict[str, Any]], problems: list[str]
) -> dict[str, dict[str, dict[str, Any]]]:
    if judgments is None:
        return {}
    if not isinstance(judgments, dict) or judgments.get("schema") != JUDGMENTS_SCHEMA:
        problems.append(f"judgments: schema must be {JUDGMENTS_SCHEMA}")
        return {}
    if judgments.get("manifest_sha256") != manifest.sha256 or judgments.get("capture_sha256") != capture_sha:
        problems.append("judgments: manifest/capture hashes do not match the recomputed hashes")
    if not isinstance(judgments.get("judge"), str) or not judgments["judge"].strip():
        problems.append("judgments: judge is required")
    cases = {case.id: case for case in manifest.cases}
    accepted: dict[str, dict[str, dict[str, Any]]] = {}
    hits_by_case = judgments.get("hits", {})
    if not isinstance(hits_by_case, dict):
        problems.append("judgments: hits must be an object of case ids")
        return {}
    for case_id, by_key in hits_by_case.items():
        if case_id not in cases or case_id not in records:
            problems.append(f"judgments: unknown case {case_id!r}")
            continue
        if not isinstance(by_key, dict):
            problems.append(f"judgments {case_id}: must be an object of evidence keys")
            continue
        hits = records[case_id].get("hits") or []
        _judge_case(case_id, by_key, cases[case_id], hits, manifest, accepted, problems)
    return accepted


def _judge_case(
    case_id: str, by_key: dict[str, Any], case: Case, hits: list[dict[str, Any]], manifest: Manifest,
    accepted: dict[str, dict[str, dict[str, Any]]], problems: list[str],
) -> None:
    known = {hit["evidence_key"]: hit for hit in hits if isinstance(hit, dict) and "evidence_key" in hit}
    group_of = {hit["evidence_key"]: group for group in _identities(list(known.values())) for hit in group}
    fact_ids = {fact.id for fact in case.facts}
    for key, judgment in by_key.items():
        where = f"judgments {case_id}/{key}"
        if key not in known:
            problems.append(f"{where}: no such captured hit")
            continue
        kept = _judge_hit(where, judgment, case, group_of[key], fact_ids, manifest, problems)
        if kept is not None:
            accepted.setdefault(case_id, {})[key] = kept
    for group in _identities(hits):
        labels = {
            (accepted.get(case_id, {})[hit["evidence_key"]]["label"],
             tuple(accepted.get(case_id, {})[hit["evidence_key"]]["supports"]))
            for hit in group
            if hit["evidence_key"] in accepted.get(case_id, {})
        }
        if len(labels) > 1:
            problems.append(f"judgments {case_id}: duplicate evidence has conflicting judgments")


def _judge_hit(
    where: str, judgment: Any, case: Case, group: list[dict[str, Any]], fact_ids: set[str], manifest: Manifest,
    problems: list[str],
) -> dict[str, Any] | None:
    """The accepted judgment of one captured hit, or ``None`` when it is refused outright."""
    label = judgment.get("label") if isinstance(judgment, dict) else None
    supports = judgment.get("supports", []) if isinstance(judgment, dict) else None
    if label not in LABELS or not isinstance(supports, list):
        problems.append(f"{where}: label must be one of {LABELS} with a supports list")
        return None
    if not all(isinstance(item, str) for item in supports):
        problems.append(f"{where}: supports must list fact ids")
        return None
    if set(supports) - fact_ids:
        problems.append(f"{where}: supports unknown facts {sorted(set(supports) - fact_ids)}")
    if label == "irrelevant" and supports:
        problems.append(f"{where}: an irrelevant hit cannot support a fact")
    if case.kind == "no_answer" and label != "irrelevant":
        problems.append(f"{where}: a no_answer case has no relevant evidence by definition")
    if any(_excluded(item, case, manifest) is True for item in group):
        problems.append(f"{where}: an excluded hit is a leak and cannot be judged")
    prelabeled = [
        fact.id for fact in case.facts if any(ref.matches(item) for item in group for ref in fact.evidence)
    ]
    if prelabeled and label != "relevant":
        problems.append(f"{where}: prelabeled evidence for {prelabeled} cannot be judged {label}")
    return {"label": label, "supports": sorted(set(supports))}


def _hit_workspace_id(hit: dict[str, Any], case: Case, manifest: Manifest) -> str | None:
    """The hit's Workspace id, or ``None`` when it cannot be established unambiguously."""
    own = manifest.workspaces[case.workspace]
    if MODE_SCOPE[case.mode] == "single_workspace" or hit.get("bound") is False:
        return own
    if hit.get("bound") is None:
        return None
    ids = [project_id for project_id, name in manifest.workspace_names.items() if name == hit.get("workspace")]
    return ids[0] if len(ids) == 1 else None


def _excluded(hit: dict[str, Any], case: Case, manifest: Manifest) -> bool | None:
    """True for a leak, False when clean, None when a workspace exclusion cannot be checked."""
    unverifiable = False
    for exclusion in case.exclusions:
        if exclusion.kind == "evidence_key" and hit.get("evidence_key") == exclusion.value:
            return True
        if exclusion.kind == "source_id" and hit.get("source_id") == exclusion.value:
            return True
        if exclusion.kind == "workspace_id":
            workspace_id = _hit_workspace_id(hit, case, manifest)
            if workspace_id is None:
                unverifiable = True
            elif workspace_id == exclusion.value:
                return True
    return None if unverifiable else False
