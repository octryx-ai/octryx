"""Seed documents, evidence payloads and reports of the default Python Engineering Knowledge Pack."""

from __future__ import annotations

import json
from typing import Any

from ...time_utils import utc_now_aware
from ._python_default_pack_seed_data import (
    PYTHON312_SOURCE_SPECS,
    PYTHON312_SOURCE_VERSIONS,
    PYTHON312_TARGETS,
)

_STACK_KEY = "python"
_ACQUISITION_MODE = "curated_seed_snapshot"


def _evidence_payload(spec: dict[str, Any], checksum: str) -> dict[str, Any]:
    return {
        "source_key": spec["source_key"],
        "title": spec["title"],
        "source_uri": spec["source_uri"],
        "official_source_uri": spec["source_uri"],
        "final_uri": spec["source_uri"],
        "source_type": spec["source_type"],
        "trust_tier": spec["trust_tier"],
        "version_label": spec["version_label"],
        "checksum": checksum,
        "fetch_status": "fetched",
        "freshness_status": "fresh",
        "fetched_at": utc_now_aware().isoformat(),
        "acquisition_mode": _ACQUISITION_MODE,
        "seed_snapshot": True,
    }


def _seed_document(spec: dict[str, Any]) -> str:
    tags = ", ".join([_STACK_KEY, *list(spec.get("tags") or [])])
    metadata = json.dumps(spec.get("metadata") or {}, indent=2, sort_keys=True)
    return (
        f"# {spec['title']}\n\n"
        f"Official source URI: {spec['source_uri']}\n\n"
        f"Acquisition mode: {_ACQUISITION_MODE}.\n\n"
        f"Summary: {spec['summary']}\n\n"
        f"Tags: {tags}\n\n"
        f"Version metadata:\n\n```json\n{metadata}\n```\n"
    )


def _build_compatibility_facts(manifest: dict[str, Any]) -> dict[str, Any]:
    quality_inputs = dict(manifest.get("quality_inputs") or {})
    return {
        "schema_version": 1,
        "stack_key": _STACK_KEY,
        "source_versions": PYTHON312_SOURCE_VERSIONS,
        "target_versions": PYTHON312_TARGETS,
        "target_version_policy": {"python": "exact_minor"},
        "source_type_counts": quality_inputs.get("source_type_counts") or {},
        "trust_tier_counts": quality_inputs.get("trust_tier_counts") or {},
        "target_version_exactness": quality_inputs.get("target_version_exactness") or {},
        "toolchain_coordinates": ["python", "ruff", "pytest", "mypy", "bandit", "semgrep"],
    }


def _build_quality_report(manifest: dict[str, Any]) -> dict[str, Any]:
    sources = list(manifest.get("sources") or [])
    archived_count = sum(1 for source in sources if source.get("fetch_status") == "fetched" and source.get("checksum"))
    quality_inputs = dict(manifest.get("quality_inputs") or {})
    return {
        "schema_version": 1,
        "passed": True,
        "seed_snapshot": True,
        "acquisition_mode": _ACQUISITION_MODE,
        "archived_source_count": archived_count,
        "planned_source_count": len(PYTHON312_SOURCE_SPECS),
        "quality_inputs": quality_inputs,
        "required_exact_targets": quality_inputs.get("target_version_exactness") or {},
        "blockers": [],
    }
