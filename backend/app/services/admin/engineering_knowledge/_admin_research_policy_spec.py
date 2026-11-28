"""Validation of research policy specs."""

from __future__ import annotations

import copy
import re
from typing import Any

from fastapi import HTTPException

_PROFILE_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,119}$")
_VALID_PROFILE_STATUSES = {"active", "archived", "draft"}
_VALID_VERSION_STATUSES = {"draft", "published", "archived"}
_VALID_RESEARCH_SOURCE_MODES = {"web", "research", "deep", "literature", "scientific", "scholarly", "auto"}
_VALID_LITERATURE_PUBLICATION_TYPES = {
    "journal-article",
    "conference-paper",
    "review",
    "systematic-review",
    "meta-analysis",
    "book-chapter",
    "preprint",
    "working-paper",
    "draft",
    "preview",
}

Issues = list[dict[str, str]]


def _as_dict(value: Any) -> dict[str, Any]:
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _as_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def _list_has_only_strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)


def _check_research_strategy(payload: dict[str, Any], errors: Issues, warnings: Issues) -> int:
    strategy = _as_dict(payload.get("research_strategy"))
    min_sources = _as_int(strategy.get("min_source_count"), default=0)
    target_sources = _as_int(strategy.get("target_source_count"), default=0)
    max_sources = _as_int(strategy.get("max_source_count"), default=0)
    if min_sources < 1:
        errors.append({"field": "research_strategy.min_source_count", "message": "must be at least 1"})
    if target_sources < min_sources:
        errors.append(
            {"field": "research_strategy.target_source_count", "message": "must be greater than or equal to min"}
        )
    if max_sources < target_sources:
        errors.append(
            {"field": "research_strategy.max_source_count", "message": "must be greater than or equal to target"}
        )
    if max_sources > 200:
        warnings.append(
            {"field": "research_strategy.max_source_count", "message": "very high source caps can be costly"}
        )
    return max_sources


def _check_output_policy(payload: dict[str, Any], errors: Issues) -> None:
    output_policy = _as_dict(payload.get("output_policy"))
    target_pages = _as_dict(output_policy.get("target_pages"))
    min_pages = _as_int(target_pages.get("min"), default=0)
    target_page_count = _as_int(target_pages.get("target"), default=0)
    max_pages = _as_int(target_pages.get("max"), default=0)
    if target_pages and not (1 <= min_pages <= target_page_count <= max_pages):
        errors.append({"field": "output_policy.target_pages", "message": "must satisfy min <= target <= max"})


def _check_delegation_policy(payload: dict[str, Any], errors: Issues) -> None:
    delegation_policy = _as_dict(payload.get("delegation_policy"))
    max_child_agents = _as_int(delegation_policy.get("max_child_agents"), default=0)
    if max_child_agents < 0 or max_child_agents > 5:
        errors.append({"field": "delegation_policy.max_child_agents", "message": "must be between 0 and 5"})
    child_runtime_timeout = _as_int(delegation_policy.get("child_runtime_timeout_seconds"), default=90)
    if not (30 <= child_runtime_timeout <= 300):
        errors.append(
            {
                "field": "delegation_policy.child_runtime_timeout_seconds",
                "message": "must be between 30 and 300",
            }
        )
    child_group_timeout = _as_int(delegation_policy.get("child_group_timeout_seconds"), default=900)
    if not (30 <= child_group_timeout <= 10_800):
        errors.append(
            {
                "field": "delegation_policy.child_group_timeout_seconds",
                "message": "must be between 30 and 10800",
            }
        )


def _check_evidence_archive(payload: dict[str, Any], errors: Issues) -> None:
    evidence_archive = _as_dict(payload.get("evidence_archive"))
    if evidence_archive.get("enabled") is not True:
        errors.append({"field": "evidence_archive.enabled", "message": "must stay enabled"})
    if str(evidence_archive.get("workspace_folder") or "").strip() != "research":
        errors.append({"field": "evidence_archive.workspace_folder", "message": "must be research"})
    for field in ("preserve_raw_sources", "preserve_parsed_text", "write_source_manifests", "write_bundle_manifest"):
        if evidence_archive.get(field) is not True:
            errors.append({"field": f"evidence_archive.{field}", "message": "must stay enabled"})


def _check_publication_type_lists(literature_policy: dict[str, Any], errors: Issues, warnings: Issues) -> None:
    for field in ("allowed_publication_types", "excluded_publication_types"):
        value = literature_policy.get(field)
        if value is not None and not _list_has_only_strings(value):
            errors.append({"field": f"source_policy.literature_policy.{field}", "message": "must be a string list"})
        elif isinstance(value, list):
            unsupported = [
                str(item).strip()
                for item in value
                if str(item).strip().lower() not in _VALID_LITERATURE_PUBLICATION_TYPES
            ]
            if unsupported:
                warnings.append(
                    {
                        "field": f"source_policy.literature_policy.{field}",
                        "message": f"contains custom publication types: {', '.join(unsupported)}",
                    }
                )


def _check_literature_rules(literature_policy: dict[str, Any], preferred_domains: Any, errors: Issues) -> None:
    if literature_policy.get("restrict_to_preferred_domains") is True and not preferred_domains:
        errors.append(
            {
                "field": "source_policy.literature_policy.preferred_domains",
                "message": "must be set when preferred-domain restriction is enabled",
            }
        )
    if (
        literature_policy.get("require_published_sources") is True
        and literature_policy.get("exclude_preprints") is False
    ):
        errors.append(
            {
                "field": "source_policy.literature_policy.exclude_preprints",
                "message": "must stay enabled when published-only sources are required",
            }
        )
    if (
        "min_citation_count" in literature_policy
        and _as_int(literature_policy.get("min_citation_count"), default=-1) < 0
    ):
        errors.append(
            {"field": "source_policy.literature_policy.min_citation_count", "message": "must be non-negative"}
        )


def _check_literature_policy(literature_policy: dict[str, Any], errors: Issues, warnings: Issues) -> None:
    literature_mode = str(literature_policy.get("mode") or "").strip().lower()
    if literature_mode and literature_mode not in _VALID_RESEARCH_SOURCE_MODES:
        errors.append({"field": "source_policy.literature_policy.mode", "message": "has an unsupported source mode"})
    preferred_domains = literature_policy.get("preferred_domains")
    if preferred_domains is not None and not _list_has_only_strings(preferred_domains):
        errors.append(
            {"field": "source_policy.literature_policy.preferred_domains", "message": "must be a string list"}
        )
    preferred_databases = literature_policy.get("preferred_databases")
    if preferred_databases is not None and not _list_has_only_strings(preferred_databases):
        errors.append(
            {"field": "source_policy.literature_policy.preferred_databases", "message": "must be a string list"}
        )
    _check_publication_type_lists(literature_policy, errors, warnings)
    _check_literature_rules(literature_policy, preferred_domains, errors)


def _check_source_policy(payload: dict[str, Any], errors: Issues, warnings: Issues) -> None:
    source_policy = _as_dict(payload.get("source_policy"))
    modalities = source_policy.get("modalities")
    if not isinstance(modalities, list) or not modalities:
        errors.append({"field": "source_policy.modalities", "message": "must contain at least one modality"})
    elif "pdf" not in {str(item).strip().lower() for item in modalities}:
        warnings.append({"field": "source_policy.modalities", "message": "PDF evidence is not enabled"})
    research_mode = str(source_policy.get("research_mode") or source_policy.get("source_mode") or "").strip().lower()
    if research_mode and research_mode not in _VALID_RESEARCH_SOURCE_MODES:
        errors.append({"field": "source_policy.research_mode", "message": "has an unsupported source mode"})
    literature_policy = _as_dict(source_policy.get("literature_policy"))
    if literature_policy:
        _check_literature_policy(literature_policy, errors, warnings)


def validate_research_policy_spec(spec: dict[str, Any] | None) -> dict[str, Any]:
    errors: Issues = []
    warnings: Issues = []
    payload = _as_dict(spec)
    if not payload:
        errors.append({"field": "spec", "message": "policy spec is required"})
    max_sources = _check_research_strategy(payload, errors, warnings)
    _check_output_policy(payload, errors)
    _check_delegation_policy(payload, errors)
    _check_evidence_archive(payload, errors)
    _check_source_policy(payload, errors, warnings)

    quality_gates = _as_dict(payload.get("quality_gates"))
    min_cited_sources = _as_int(quality_gates.get("min_cited_sources"), default=0)
    if max_sources and min_cited_sources > max_sources:
        errors.append({"field": "quality_gates.min_cited_sources", "message": "cannot exceed max source count"})
    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
    }


def _require_valid_spec(spec: dict[str, Any] | None) -> dict[str, Any]:
    diagnostics = validate_research_policy_spec(spec)
    if diagnostics["errors"]:
        raise HTTPException(
            status_code=400,
            detail={"message": "Invalid research policy spec", "diagnostics": diagnostics},
        )
    return diagnostics
