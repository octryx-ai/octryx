"""Source audit (trust, version, coverage) and freshness checks for pack sources."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from ...time_utils import utc_now
from .source_ingestion_specs import EngineeringKnowledgeSourceAudit, EngineeringKnowledgeSourceSpec

_OFFICIAL_OR_VENDOR_DOMAINS = {
    "docs.oracle.com",
    "oracle.com",
    "openjdk.org",
    "docs.spring.io",
    "spring.io",
    "jakarta.ee",
    "docs.openrewrite.org",
    "openrewrite.org",
    "docs.python.org",
    "python.org",
    "packaging.python.org",
    "docs.astral.sh",
}


def audit_engineering_knowledge_source(
    source_spec: EngineeringKnowledgeSourceSpec | dict[str, Any],
    *,
    target_versions: dict[str, Any] | None = None,
    content_text: str = "",
) -> EngineeringKnowledgeSourceAudit:
    spec = (
        source_spec
        if isinstance(source_spec, EngineeringKnowledgeSourceSpec)
        else EngineeringKnowledgeSourceSpec.from_mapping(source_spec)
    )
    metadata = dict(spec.metadata or {})
    canonical_uri = str(metadata.get("original_source_uri") or spec.source_uri or "").strip()
    blockers = _uri_and_domain_blockers(spec, canonical_uri)
    blockers.extend(_target_version_blockers(spec, canonical_uri, metadata, target_versions, content_text))

    coverage_areas = _infer_coverage_areas(spec, canonical_uri, content_text=content_text)
    if not coverage_areas:
        blockers.append("source_has_no_detectable_coverage_area")

    if blockers:
        return EngineeringKnowledgeSourceAudit(
            status="rejected",
            reason="; ".join(blockers),
            canonical_uri=canonical_uri,
            coverage_areas=coverage_areas,
            blockers=blockers,
        )
    return EngineeringKnowledgeSourceAudit(
        status="accepted",
        reason="Canonical source matches trust, version, and coverage requirements.",
        canonical_uri=canonical_uri,
        coverage_areas=coverage_areas,
    )


def _uri_and_domain_blockers(spec: EngineeringKnowledgeSourceSpec, canonical_uri: str) -> list[str]:
    parsed = urlsplit(canonical_uri)
    blockers: list[str] = []
    if parsed.scheme not in {"http", "https"}:
        blockers.append("canonical_source_uri_must_be_http")
    if spec.source_uri.startswith("context7://") or canonical_uri.startswith("context7://"):
        blockers.append("context7_snippets_are_source_candidates_only")

    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if spec.trust_tier in {"official", "vendor"} and host:
        allowed_domain = any(host == domain or host.endswith(f".{domain}") for domain in _OFFICIAL_OR_VENDOR_DOMAINS)
        if not allowed_domain:
            blockers.append("official_or_vendor_source_domain_is_not_allowlisted")
    return blockers


def _target_version_blockers(
    spec: EngineeringKnowledgeSourceSpec,
    canonical_uri: str,
    metadata: dict[str, Any],
    target_versions: dict[str, Any] | None,
    content_text: str,
) -> list[str]:
    target_versions = dict(target_versions or {})
    if not target_versions:
        return []
    version_text = " ".join(
        [
            spec.title,
            spec.source_uri,
            canonical_uri,
            spec.version_label,
            json.dumps(metadata, sort_keys=True),
            content_text,
        ]
    ).lower()
    missing_versions = [
        f"{coordinate}:{version}"
        for coordinate, version in target_versions.items()
        if str(version or "").strip() and str(version or "").strip().lower() not in version_text
    ]
    if missing_versions:
        return ["source_does_not_reference_target_versions:" + ",".join(missing_versions)]
    return []


def _infer_coverage_areas(
    spec: EngineeringKnowledgeSourceSpec,
    canonical_uri: str,
    *,
    content_text: str = "",
) -> list[str]:
    text = " ".join([spec.source_key, spec.title, spec.source_type, canonical_uri, content_text]).lower()
    areas: set[str] = set()
    if any(term in text for term in ["migration", "migrate"]):
        areas.add("migration")
    if any(term in text for term in ["release", "relnotes", "jep", "project", "feature"]):
        areas.add("release_notes")
    if any(term in text for term in ["deprecated", "removal", "breaking"]):
        areas.add("removals_deprecations")
    if any(term in text for term in ["api", "documentation", "reference", "docs"]):
        areas.add("api_reference")
    if any(term in text for term in ["tool", "tooling", "maven", "gradle", "recipe", "openrewrite", "compiler"]):
        areas.add("tooling")
    if any(term in text for term in ["security", "crypto", "jni", "unsafe"]):
        areas.add("security_native")
    return sorted(areas)


def evaluate_source_freshness(
    *,
    fetched_at: datetime | None,
    freshness_policy: dict[str, Any] | None,
    now: datetime | None = None,
) -> str:
    if fetched_at is None:
        return "unknown"
    policy = dict(freshness_policy or {})
    ttl_days = int(policy.get("ttl_days") or 0)
    warning_days = int(policy.get("warning_days") or max(ttl_days - 7, 0))
    current = now or utc_now()
    age = current - fetched_at
    if ttl_days > 0 and age > timedelta(days=ttl_days):
        return "stale"
    if warning_days > 0 and age > timedelta(days=warning_days):
        return "warning"
    return "fresh"

