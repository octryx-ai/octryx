"""Shared constants and normalization helpers for design artifacts."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

RECOMMENDED_DESIGN_ARTIFACTS: tuple[dict[str, Any], ...] = (
    {
        "artifact_kind": "outcome_brief",
        "label": "Outcome Brief",
        "description": "Problem, target users, business outcome, non-goals and success metrics.",
        "required_by_default": True,
        "order_index": 10,
    },
    {
        "artifact_kind": "prd",
        "label": "PRD",
        "description": "Scope, use-cases, assumptions, dependencies and measurable outcomes.",
        "required_by_default": True,
        "order_index": 20,
    },
    {
        "artifact_kind": "acceptance_criteria",
        "label": "Acceptance Criteria",
        "description": "Example-driven acceptance cases, edge cases and verification rules.",
        "required_by_default": True,
        "order_index": 30,
    },
    {
        "artifact_kind": "architecture",
        "label": "Architecture",
        "description": "C4-light architecture view, boundaries, flows and non-functional constraints.",
        "required_by_default": False,
        "order_index": 40,
    },
    {
        "artifact_kind": "adr",
        "label": "ADR",
        "description": "Architecture decision records with trade-offs and consequences.",
        "required_by_default": False,
        "order_index": 50,
    },
    {
        "artifact_kind": "contract",
        "label": "Contract",
        "description": "API, schema or event contract for cross-boundary integration.",
        "required_by_default": False,
        "order_index": 60,
    },
    {
        "artifact_kind": "definition_of_done",
        "label": "Definition of Done",
        "description": "Mandatory quality gates, release checks and operational readiness rules.",
        "required_by_default": True,
        "order_index": 70,
    },
)

DEFAULT_ARTIFACT_KIND = "note"
ALLOWED_ARTIFACT_STATUSES = {"draft", "review", "approved", "superseded", "archived"}
ALLOWED_TRACE_TARGET_TYPES = {"task", "session", "code_repository", "pull_request", "release", "checkpoint"}
ALLOWED_TRACE_STATUSES = {"planned", "active", "completed", "superseded", "archived"}


def list_recommended_design_artifacts() -> list[dict[str, Any]]:
    return [dict(item) for item in RECOMMENDED_DESIGN_ARTIFACTS]


def normalize_artifact_kind(value: str | None) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return normalized or DEFAULT_ARTIFACT_KIND


def normalize_artifact_status(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in ALLOWED_ARTIFACT_STATUSES else "draft"


def normalize_metadata(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def normalize_trace_target_type(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in ALLOWED_TRACE_TARGET_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported trace target_type")
    return normalized


def normalize_trace_status(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in ALLOWED_TRACE_STATUSES else "active"


def normalize_id_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    normalized: list[str] = []
    for item in value:
        token = str(item or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        normalized.append(token)
    return normalized


def artifact_links_from_payload(payload: dict[str, Any]) -> dict[str, list[str]]:
    raw_metadata = normalize_metadata(payload.get("metadata_json"))
    linked_repository_ids = normalize_id_list(
        payload.get("linked_repository_ids")
        if "linked_repository_ids" in payload
        else raw_metadata.get("linked_repository_ids")
    )
    depends_on_artifact_ids = normalize_id_list(
        payload.get("depends_on_artifact_ids")
        if "depends_on_artifact_ids" in payload
        else raw_metadata.get("depends_on_artifact_ids")
    )
    return {
        "linked_repository_ids": linked_repository_ids,
        "depends_on_artifact_ids": depends_on_artifact_ids,
    }


def merge_artifact_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = normalize_metadata(payload.get("metadata_json"))
    links = artifact_links_from_payload(payload)
    metadata["linked_repository_ids"] = links["linked_repository_ids"]
    metadata["depends_on_artifact_ids"] = links["depends_on_artifact_ids"]
    return metadata


def recommended_map() -> dict[str, dict[str, Any]]:
    return {str(item["artifact_kind"]): dict(item) for item in RECOMMENDED_DESIGN_ARTIFACTS}


def artifact_template_markdown(template: dict[str, Any]) -> str:
    label = str(template.get("label") or "Artifact").strip()
    description = str(template.get("description") or "").strip()
    return "\n".join(
        [
            f"# {label}",
            "",
            description or "Document the decision-quality information for this artifact.",
            "",
            "## Context",
            "- Problem:",
            "- Scope:",
            "- Assumptions:",
            "",
            "## Decision / Content",
            "-",
            "",
            "## Verification",
            "-",
            "",
            "## Risks / Open Questions",
            "-",
        ]
    ).strip()
