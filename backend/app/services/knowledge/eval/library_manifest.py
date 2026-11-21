"""Frozen inputs of the read-only Library evaluation: manifest, prior queries, evidence inventory.

A manifest is frozen before any capture. It names the cases, their required facts with equivalent evidence
alternatives, the exclusions, the declared principal and environment, and a request budget that may not
exceed the hard ceilings below. Two further offline inputs are root-provided and immutable:

* prior queries: every query already used (the ``spring_boot`` golden set is always included). A holdout case whose
  normalized query matches one is refused. Equality detects known reuse only; it does not certify novelty.
* an evidence inventory: which labelled spans exist, with verification provenance. Without it, required
  evidence stays unverified and no holdout case is eligible for acceptance.

Every document is hashed from its canonical content (sorted keys, compact UTF-8), never from a stored field.
Nothing here performs I/O beyond reading the given files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .library_cases import _budget, _case
from .library_inputs import (
    LOGICAL_PROVIDER_OPS,
    MANIFEST_SCHEMA,
    MAX_RESULT_LIMIT,
    PRIOR_QUERIES_SCHEMA,
    Case,
    EvaluationInputError,
    Manifest,
    canonical_sha256,
    is_identifier,
    load_json,
    normalize_query,
    parse_timestamp,
)


def spring_boot_golden_queries() -> list[str]:
    from .golden import load_golden_set

    return [query.question for query in load_golden_set("spring_boot").queries]


def load_prior_queries(paths: list[str | Path]) -> tuple[set[str], list[dict[str, Any]]]:
    """Normalized prior queries plus provenance; accepts prior_queries/v1 or a frozen case document."""
    queries = spring_boot_golden_queries()
    provenance: list[dict[str, Any]] = [{"source": "golden:spring_boot", "queries": len(queries)}]
    normalized = {normalize_query(query) for query in queries}
    for path in paths:
        document = load_json(path)
        if isinstance(document, dict) and document.get("schema") == PRIOR_QUERIES_SCHEMA:
            items = document.get("queries")
        elif isinstance(document, dict) and isinstance(document.get("cases"), list):
            items = [case.get("query") for case in document["cases"] if isinstance(case, dict)]
        else:
            raise EvaluationInputError([f"{path}: not a prior_queries/v1 or frozen case document"])
        if not isinstance(items, list) or not all(isinstance(item, str) and item.strip() for item in items):
            raise EvaluationInputError([f"{path}: queries must be non-empty strings"])
        normalized |= {normalize_query(item) for item in items}
        provenance.append({"source": Path(path).name, "sha256": canonical_sha256(document), "queries": len(items)})
    return normalized, provenance


def _workspace_aliases(document: dict[str, Any], problems: list[str]) -> dict[str, str]:
    aliases_raw = document.get("workspaces")
    aliases: dict[str, str] = {}
    if isinstance(aliases_raw, dict):
        for alias, spec in aliases_raw.items():
            project_id = spec.get("id") if isinstance(spec, dict) else None
            if not is_identifier(alias) or not is_identifier(project_id):
                problems.append(f"workspaces: {alias!r} needs a valid id")
            else:
                aliases[alias] = project_id
    if not aliases:
        problems.append("manifest: at least one workspace is required")
    return aliases


def _workspace_names(document: dict[str, Any], problems: list[str]) -> dict[str, str]:
    names_raw = document.get("workspace_name_map") or {}
    names: dict[str, str] = {}
    if not isinstance(names_raw, dict):
        problems.append("workspace_name_map must map project ids to names")
        return names
    for project_id, name in names_raw.items():
        if not is_identifier(project_id) or not isinstance(name, str) or not name.strip():
            problems.append(f"workspace_name_map: invalid entry {project_id!r}")
        else:
            names[project_id] = name
    collisions = sorted({name for name in names.values() if list(names.values()).count(name) > 1})
    if collisions:
        problems.append(f"workspace_name_map: names are ambiguous: {collisions}")
    return names


def _check_cases_in_budget(cases: list[Case], budget: dict[str, int], problems: list[str]) -> None:
    ids = [case.id for case in cases]
    if len(set(ids)) != len(ids):
        problems.append("manifest: duplicate case id")
    if budget and len(cases) > budget.get("max_search_requests", 0):
        problems.append(f"budget: {len(cases)} cases exceed max_search_requests {budget.get('max_search_requests')}")
    for case in cases:
        if case.limit > budget.get("max_result_limit", MAX_RESULT_LIMIT):
            problems.append(f"case {case.id}: limit exceeds budget.max_result_limit")
    estimate = sum(LOGICAL_PROVIDER_OPS[case.mode] for case in cases)
    if budget and estimate > budget.get("max_logical_provider_ops", 0):
        problems.append(f"budget: estimated {estimate} logical provider operations exceed the budget")


def _overlap_check(
    cases: list[Case], prior_query_paths: list[str | Path] | None, problems: list[str]
) -> dict[str, Any]:
    overlap_check: dict[str, Any] = {"performed": False, "matches": [], "provenance": []}
    holdout = [case for case in cases if case.split == "holdout"]
    if holdout and not prior_query_paths:
        problems.append("holdout cases require the prior-query input (including the historical cases)")
    elif prior_query_paths is not None or holdout:
        prior, provenance = load_prior_queries(list(prior_query_paths or []))
        matches = [case.id for case in cases if normalize_query(case.query) in prior]
        overlap_check = {
            "performed": True,
            "method": "normalized exact query equality; does not certify semantic novelty",
            "matches": matches,
            "provenance": provenance,
        }
        reused = [case.id for case in holdout if case.id in matches]
        if reused:
            problems.append(f"holdout cases reuse prior queries: {reused}")
    return overlap_check


def load_manifest(document: dict[str, Any], *, prior_query_paths: list[str | Path] | None = None) -> Manifest:
    """Validate a manifest completely; any problem refuses it."""
    problems: list[str] = []
    if not isinstance(document, dict) or document.get("schema") != MANIFEST_SCHEMA:
        raise EvaluationInputError([f"manifest: schema must be {MANIFEST_SCHEMA}"])
    sha = canonical_sha256(document)
    frozen_at = parse_timestamp(document.get("frozen_at"))
    if frozen_at is None:
        problems.append("manifest: frozen_at must be an ISO-8601 timestamp with an offset")
    aliases = _workspace_aliases(document, problems)
    names = _workspace_names(document, problems)
    for key in ("principal", "environment_declared"):
        if not isinstance(document.get(key), dict):
            problems.append(f"manifest: {key} must be an object (operator declaration)")
    budget = _budget(document.get("budget"), problems)
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        problems.append("manifest: cases must be a non-empty list")
        raw_cases = []
    cases = [case for index, raw in enumerate(raw_cases) if (case := _case(raw, index, aliases, names, problems))]
    _check_cases_in_budget(cases, budget, problems)
    overlap_check = _overlap_check(cases, prior_query_paths, problems)
    if problems:
        raise EvaluationInputError(problems)
    return Manifest(
        raw=document,
        sha256=sha,
        frozen_at=frozen_at,
        workspaces=aliases,
        workspace_names=names,
        budget=budget,
        cases=tuple(cases),
        overlap_check=overlap_check,
    )


__all__ = [
    "load_manifest",
    "load_prior_queries",
]
