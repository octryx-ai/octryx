"""Evidence ledger and coverage helpers for Engineering Knowledge Packs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ...models import EngineeringKnowledgePackSource
from .archive_store import engineering_archive_exists, read_engineering_archive_text

REQUIRED_COVERAGE_AREAS_BY_STACK: dict[str, tuple[str, ...]] = {
    "java": (
        "features",
        "migration",
        "removals_deprecations",
        "build_tooling",
        "runtime_performance",
        "security_native",
    ),
    "java-spring": (
        "features",
        "migration",
        "removals_deprecations",
        "build_tooling",
        "runtime_performance",
        "security_native",
        "framework_dependencies",
    ),
    "python": (
        "features",
        "migration",
        "removals_deprecations",
        "build_tooling",
    ),
}


def build_evidence_ledger(
    *,
    sources: list[EngineeringKnowledgePackSource],
    archive_base_path: Path,
    stack_key: str,
    target_versions: dict[str, Any],
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for source in sources:
        source_audit = dict(dict(source.source_metadata or {}).get("source_audit") or {})
        if str(source_audit.get("status") or "") not in {"accepted", "limited"}:
            continue
        if not source.parsed_archive_path:
            continue
        if not engineering_archive_exists(source.parsed_archive_path, archive_base_path=archive_base_path):
            continue
        content = read_engineering_archive_text(source.parsed_archive_path, archive_base_path=archive_base_path)
        facts.extend(
            _facts_from_source(
                source=source,
                content=content,
                source_audit=source_audit,
                stack_key=stack_key,
                target_versions=target_versions,
            )
        )
    return facts


def build_coverage_matrix(
    *,
    evidence_ledger: list[dict[str, Any]],
    stack_key: str,
) -> dict[str, Any]:
    required_areas = REQUIRED_COVERAGE_AREAS_BY_STACK.get(stack_key) or ("features", "migration", "build_tooling")
    by_area: dict[str, dict[str, Any]] = {}
    for area in required_areas:
        area_facts = [
            fact
            for fact in evidence_ledger
            if area in set(fact.get("coverage_areas") or [])
            and fact.get("usable_for_pack") is True
        ]
        source_keys = sorted({str(fact.get("source_key") or "") for fact in area_facts if fact.get("source_key")})
        by_area[area] = {
            "status": "covered" if area_facts else "missing",
            "fact_count": len(area_facts),
            "source_keys": source_keys,
        }
    missing_areas = [area for area, coverage in by_area.items() if coverage["status"] != "covered"]
    return {
        "schema_version": 1,
        "required_areas": list(required_areas),
        "covered_area_count": len(required_areas) - len(missing_areas),
        "missing_areas": missing_areas,
        "areas": by_area,
        "passed": not missing_areas,
    }


def _facts_from_source(
    *,
    source: EngineeringKnowledgePackSource,
    content: str,
    source_audit: dict[str, Any],
    stack_key: str,
    target_versions: dict[str, Any],
) -> list[dict[str, Any]]:
    chunks = _candidate_chunks(content)
    facts: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks[:24], start=1):
        areas = _infer_fact_coverage_areas(chunk, source=source, source_audit=source_audit, stack_key=stack_key)
        if not areas:
            continue
        claim = _normalize_claim(chunk)
        if not claim:
            continue
        facts.append(
            {
                "fact_id": f"{source.source_key}-fact-{index}",
                "claim": claim,
                "category": _primary_category(areas),
                "coverage_areas": areas,
                "source_id": source.id,
                "source_key": source.source_key,
                "source_uri": source.source_uri,
                "archive_path": source.parsed_archive_path,
                "excerpt": chunk[:700],
                "confidence": 0.9 if source.trust_tier == "official" else 0.8,
                "usable_for_pack": True,
                "target_versions": dict(target_versions or {}),
            }
        )
    return facts


def _candidate_chunks(content: str) -> list[str]:
    normalized = content.replace("\r\n", "\n")
    chunks: list[str] = []
    for number, title in re.findall(r"(?m)(\d{3}):\s+\[([^\]]+)\]\([^)]+\)", normalized):
        chunks.append(f"JEP {number}: {title}")
    current_heading = ""
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            text = " ".join(paragraph).strip()
            paragraph.clear()
            if _is_reviewable_chunk(text):
                chunks.append(" — ".join(part for part in [current_heading, text] if part))

    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            continue
        if line.startswith("#"):
            flush_paragraph()
            current_heading = line.strip("# ").strip()
            continue
        if line.startswith(("-", "*")) or re.match(r"^\d+[.)]\s+", line):
            flush_paragraph()
            bullet = line.lstrip("-* 0123456789.)")
            if _is_reviewable_chunk(bullet):
                chunks.append(" — ".join(part for part in [current_heading, bullet] if part))
            continue
        paragraph.append(line)
    flush_paragraph()
    return chunks


def _is_reviewable_chunk(text: str) -> bool:
    normalized = " ".join(str(text or "").split())
    if len(normalized) < 40:
        return bool(re.match(r"^JEP\s+\d{3}:", normalized))
    lower = normalized.lower()
    if lower in {"getting started", "next steps"}:
        return False
    if lower.startswith(("accessibility", "oracle account", "sign-in", "sign out", "country")):
        return False
    if re.fullmatch(r"\[.*?\]\([^)]+\)", normalized):
        return False
    return True


def _infer_fact_coverage_areas(
    text: str,
    *,
    source: EngineeringKnowledgePackSource,
    source_audit: dict[str, Any],
    stack_key: str,
) -> list[str]:
    haystack = " ".join(
        [
            text,
            source.source_key,
            source.title,
            source.source_type,
            " ".join(str(area) for area in source_audit.get("coverage_areas") or []),
            stack_key,
        ]
    ).lower()
    areas: set[str] = set()
    if any(term in haystack for term in ["feature", "jep", "language", "api", "source files", "module import"]):
        areas.add("features")
    if any(term in haystack for term in ["migration", "migrate", "upgrade", "compatibility"]):
        areas.add("migration")
    if any(term in haystack for term in ["removal", "removed", "deprecated", "deprecation", "breaking"]):
        areas.add("removals_deprecations")
    if any(term in haystack for term in ["maven", "gradle", "compiler", "--release", "build", "tool", "runtime image"]):
        areas.add("build_tooling")
    if any(term in haystack for term in ["runtime", "performance", "jfr", "gc", "shenandoah", "aot", "profiling"]):
        areas.add("runtime_performance")
    if any(term in haystack for term in ["security", "crypto", "jni", "unsafe", "manager", "key derivation"]):
        areas.add("security_native")
    if "spring" in haystack or "dependency" in haystack or "bom" in haystack:
        areas.add("framework_dependencies")
    return sorted(areas)


def _normalize_claim(text: str) -> str:
    claim = " ".join(str(text or "").split())
    claim = re.sub(r"^[-*]\s*", "", claim)
    claim = re.sub(r"\]\(([^)]+)\)", "", claim)
    claim = claim.replace("[", "").replace("]", "")
    return claim[:500]


def _primary_category(coverage_areas: list[str]) -> str:
    return coverage_areas[0] if coverage_areas else "general"
