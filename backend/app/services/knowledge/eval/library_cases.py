"""Validation of one manifest case and of the manifest budget; every problem is collected."""

from __future__ import annotations

import re
from typing import Any

from .library_inputs import (
    KINDS,
    MAX_LOGICAL_PROVIDER_OPS,
    MAX_RESULT_LIMIT,
    MAX_SEARCH_REQUESTS,
    MAX_SOURCE_READS,
    MAX_TIMEOUT_S,
    MODES,
    SPLITS,
    Case,
    EvidenceRef,
    Exclusion,
    Fact,
    is_identifier,
)


def _items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _ref(raw: Any, where: str, problems: list[str]) -> EvidenceRef | None:
    if not isinstance(raw, dict):
        problems.append(f"{where}: evidence alternative must be an object")
        return None
    if set(raw) == {"evidence_key"} and is_identifier(raw["evidence_key"]):
        return EvidenceRef(evidence_key=raw["evidence_key"])
    if set(raw) == {"source_id", "content_sha256", "span_ordinal"}:
        sha, ordinal = raw["content_sha256"], raw["span_ordinal"]
        if (
            is_identifier(raw["source_id"])
            and isinstance(sha, str)
            and re.fullmatch(r"[0-9a-f]{64}", sha)
            and isinstance(ordinal, int)
            and not isinstance(ordinal, bool)
            and ordinal >= 1  # KnowledgeEvidenceSpan.span_ordinal is one-based (ck_..._ordinal_positive)
        ):
            return EvidenceRef(source_id=raw["source_id"], content_sha256=sha, span_ordinal=ordinal)
    problems.append(f"{where}: evidence alternative is neither an evidence_key nor a source/hash/ordinal span")
    return None


def _case(raw: Any, index: int, aliases: dict[str, str], names: dict[str, str], problems: list[str]) -> Case | None:
    where = f"case[{index}]"
    if not isinstance(raw, dict):
        problems.append(f"{where}: must be an object")
        return None
    case_id = raw.get("id")
    if not is_identifier(case_id):
        problems.append(f"{where}: invalid id")
        return None
    where = f"case {case_id}"
    split, kind, mode = raw.get("split"), raw.get("kind"), raw.get("mode")
    _check_case_fields(raw, where, aliases, problems)
    query, limit = raw.get("query"), raw.get("limit")
    products, version = raw.get("products"), raw.get("version")
    facts = _case_facts(raw, where, problems)
    exclusions = _case_exclusions(raw, where, names, problems)
    _check_case_consistency(kind, facts, exclusions, where, problems)
    return Case(
        id=case_id,
        split=split if split in SPLITS else "",
        kind=kind if kind in KINDS else "",
        workspace=raw["workspace"] if isinstance(raw.get("workspace"), str) else "",
        mode=mode if mode in MODES else "lexical",
        query=query if isinstance(query, str) else "",
        limit=limit if isinstance(limit, int) else 0,
        products=tuple(products) if isinstance(products, list) else None,
        version=version if isinstance(version, str) else None,
        facts=tuple(facts),
        exclusions=tuple(exclusions),
    )


def _check_case_fields(raw: dict[str, Any], where: str, aliases: dict[str, str], problems: list[str]) -> None:
    split, kind, mode = raw.get("split"), raw.get("kind"), raw.get("mode")
    if split not in SPLITS:
        problems.append(f"{where}: split must be one of {SPLITS}")
    if kind not in KINDS:
        problems.append(f"{where}: kind must be one of {KINDS}")
    if mode not in MODES:
        problems.append(f"{where}: mode must be one of {MODES}")
    if not isinstance(raw.get("workspace"), str) or raw["workspace"] not in aliases:
        problems.append(f"{where}: undeclared workspace")
    query = raw.get("query")
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        problems.append(f"{where}: query must be 1-2000 characters")
    limit = raw.get("limit")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_RESULT_LIMIT:
        problems.append(f"{where}: limit must be 1-{MAX_RESULT_LIMIT}")
    products = raw.get("products")
    if products is not None and (
        not isinstance(products, list) or not all(isinstance(item, str) and item for item in products)
    ):
        problems.append(f"{where}: products must be a list of names or null")
    version = raw.get("version")
    if version is not None and not isinstance(version, str):
        problems.append(f"{where}: version must be a string or null")


def _case_facts(raw: dict[str, Any], where: str, problems: list[str]) -> list[Fact]:
    facts: list[Fact] = []
    for key in ("facts", "excluded"):
        if raw.get(key) is not None and not isinstance(raw[key], list):
            problems.append(f"{where}: {key} must be a list")
    for fact_index, fact_raw in enumerate(_items(raw.get("facts"))):
        fact_id = fact_raw.get("id") if isinstance(fact_raw, dict) else None
        if not is_identifier(fact_id) or not isinstance(fact_raw.get("required"), bool):
            problems.append(f"{where}: fact[{fact_index}] needs an id and a boolean 'required'")
            continue
        evidence = fact_raw.get("evidence")
        if not isinstance(evidence, list):
            problems.append(f"{where}: fact {fact_id} evidence must be a list")
        alternatives = [_ref(item, f"{where} fact {fact_id}", problems) for item in _items(evidence)]
        if not alternatives:
            problems.append(f"{where}: fact {fact_id} needs at least one evidence alternative")
        facts.append(Fact(fact_id, fact_raw["required"], tuple(ref for ref in alternatives if ref is not None)))
    if len({fact.id for fact in facts}) != len(facts):
        problems.append(f"{where}: duplicate fact id")
    return facts


def _case_exclusions(raw: dict[str, Any], where: str, names: dict[str, str], problems: list[str]) -> list[Exclusion]:
    exclusions: list[Exclusion] = []
    for exclusion_raw in _items(raw.get("excluded")):
        if not isinstance(exclusion_raw, dict) or len(exclusion_raw) != 1:
            problems.append(f"{where}: an exclusion names exactly one evidence_key, source_id or workspace_id")
            continue
        ((exclusion_kind, value),) = exclusion_raw.items()
        if exclusion_kind not in ("evidence_key", "source_id", "workspace_id") or not is_identifier(value):
            problems.append(f"{where}: unsupported exclusion {exclusion_kind!r}")
            continue
        if exclusion_kind == "workspace_id" and value not in names:
            # Hits name their Workspace, not its id: without a root-provided map the check cannot be made.
            problems.append(f"{where}: workspace exclusion {value} is not in workspace_name_map")
            continue
        exclusions.append(Exclusion(exclusion_kind, value))
    return exclusions


def _check_case_consistency(
    kind: Any, facts: list[Fact], exclusions: list[Exclusion], where: str, problems: list[str]
) -> None:
    required = [fact for fact in facts if fact.required]
    if kind == "answer" and not required:
        problems.append(f"{where}: an answer case needs at least one required fact")
    if kind == "no_answer" and facts:
        problems.append(f"{where}: a no_answer case has no facts")
    if kind == "exclusion" and not exclusions:
        problems.append(f"{where}: an exclusion case needs at least one exclusion")
    supporting = {ref.label() for fact in facts for ref in fact.evidence}
    excluded_keys = {f"key:{item.value}" for item in exclusions if item.kind == "evidence_key"}
    excluded_sources = {item.value for item in exclusions if item.kind == "source_id"}
    contradictory = supporting & excluded_keys
    contradictory |= {
        ref.label() for fact in facts for ref in fact.evidence if ref.source_id and ref.source_id in excluded_sources
    }
    if contradictory:
        problems.append(f"{where}: evidence both supports a fact and is excluded: {sorted(contradictory)}")


def _budget(raw: Any, problems: list[str]) -> dict[str, int]:
    ceilings = {
        "max_search_requests": MAX_SEARCH_REQUESTS,
        "max_result_limit": MAX_RESULT_LIMIT,
        "max_logical_provider_ops": MAX_LOGICAL_PROVIDER_OPS,
        "max_source_reads": MAX_SOURCE_READS,
        "timeout_s": MAX_TIMEOUT_S,
        "concurrency": 1,
    }
    budget: dict[str, int] = {}
    raw = raw if isinstance(raw, dict) else {}
    unknown = sorted(set(raw) - set(ceilings))
    if unknown:
        problems.append(f"budget: unknown keys {unknown}")
    for key, ceiling in ceilings.items():
        value = raw.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > ceiling:
            problems.append(f"budget: {key} must be an integer from 0 to {ceiling}")
            continue
        budget[key] = value
    if budget.get("concurrency") != 1:
        problems.append("budget: concurrency must be 1")
    if budget.get("timeout_s", 0) < 1:
        problems.append("budget: timeout_s must be at least 1")
    return budget
