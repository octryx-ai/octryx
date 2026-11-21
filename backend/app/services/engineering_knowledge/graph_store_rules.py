"""Validation rules and value normalizers for the Engineering Knowledge Graph store."""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

NODE_TYPES = {
    "agent_run",
    "build_pipeline",
    "coding_session",
    "commit",
    "decision",
    "evidence_source",
    "failure_pattern",
    "fix_pattern",
    "framework",
    "library",
    "pipeline_stage",
    "policy_finding",
    "pull_request",
    "repository",
    "reviewer",
    "runtime",
    "team",
    "technology",
    "version",
    "vulnerability",
    "work_item",
}

EDGE_TYPES = {
    "affects",
    "applies_to",
    "conflicts_with",
    "depends_on",
    "derived_from",
    "fixed_by",
    "invalidated_by",
    "learned_from",
    "observed_in",
    "owned_by",
    "published_as",
    "reviewed_by",
    "supersedes",
    "verified_by",
}

SCOPE_TYPES = {"global", "workspace", "project", "repository"}
TRUST_LEVELS = {"bronze", "silver", "gold", "official", "verified", "untrusted"}
CLASSIFICATIONS = {"public", "internal", "confidential", "restricted", "secret"}
STATUSES = {"active", "draft", "rejected", "retracted", "expired", "stale"}
BLOCKED_PAYLOAD_KEY_PARTS = {
    "access_token",
    "api_key",
    "authorization",
    "bearer",
    "client_secret",
    "cookie",
    "credential",
    "password",
    "private_key",
    "raw_log",
    "raw_payload",
    "secret",
    "session_token",
}


def _scope(
    *,
    scope_type: str,
    scope_id: str | None = None,
    workspace_id: str | None = None,
    repository_id: str | None = None,
) -> dict[str, str | None]:
    safe_type = _normalize_enum(scope_type or "global", allowed=SCOPE_TYPES, label="scope_type")
    resolved_id = str(scope_id or "").strip()
    if safe_type == "workspace":
        resolved_id = resolved_id or str(workspace_id or "").strip()
    elif safe_type == "repository":
        resolved_id = resolved_id or str(repository_id or "").strip()
    elif safe_type == "global":
        resolved_id = "global"
    if safe_type != "global" and not resolved_id:
        raise HTTPException(status_code=400, detail=f"{safe_type} scope requires scope_id")
    return {
        "scope_type": safe_type,
        "scope_id": None if safe_type == "global" else resolved_id,
        "scope_key": f"{safe_type}:{resolved_id}",
    }


def _normalize_type(value: Any, *, allowed: set[str] | None = None, label: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    text = re.sub(r"[^a-z0-9_:.]", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        raise HTTPException(status_code=400, detail=f"{label} is required")
    if allowed is not None and text not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported {label}: {text}")
    return text


def _normalize_key(value: Any, *, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail=f"{label} is required")
    if len(text) > 300:
        raise HTTPException(status_code=400, detail=f"{label} is too long")
    return text


def _normalize_alias(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _normalize_enum(value: Any, *, allowed: set[str], label: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if text not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported {label}: {text}")
    return text


def _safe_dict(value: Any, *, label: str) -> dict[str, Any]:
    payload = _as_dict(value)
    _reject_unsafe_payload(payload, label=label)
    return payload


def _safe_refs(value: Any, *, label: str) -> list[dict[str, Any]]:
    refs = [item for item in _as_list(value) if isinstance(item, dict)]
    _reject_unsafe_payload(refs, label=label)
    return refs


def _reject_unsafe_payload(value: Any, *, label: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).strip().lower()
            if any(part in normalized_key for part in BLOCKED_PAYLOAD_KEY_PARTS):
                raise HTTPException(status_code=400, detail=f"{label} contains unsafe raw secret or log field: {key}")
            _reject_unsafe_payload(item, label=f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_unsafe_payload(item, label=f"{label}[{index}]")


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None
