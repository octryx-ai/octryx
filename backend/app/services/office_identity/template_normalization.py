"""Close a template's layout gaps at upload time, without touching the original."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .diagram_layout_gaps import analyse_gaps
from .layout_authoring import GeneratedLayout, LayoutSpec
from .layout_registration import add_layouts
from .picture_safe_area import template_margin_emu
from .template_snapshot import build_template_snapshot

MANIFEST_NAME = "normalization.json"
MANIFEST_VERSION = 1


class NormalizationError(RuntimeError):
    """The template cannot be normalised — stated, never worked around."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _derived_records(
    generated: list[GeneratedLayout], derived_snapshot: dict[str, Any]
) -> list[dict[str, Any]]:
    by_part = {str(layout.get("part")): layout for layout in derived_snapshot.get("layouts", [])}
    records: list[dict[str, Any]] = []
    for item in generated:
        catalog = by_part.get(item.part)
        if catalog is None:
            raise NormalizationError(
                f"generated layout {item.part} is not in the derivative's catalog; "
                "registration is incomplete"
            )
        records.append(
            {
                "key": str(catalog.get("key")),
                "name": item.spec.name,
                "shape": item.spec.shape,
                "content_shape": str(catalog.get("content_shape")),
                "part": item.part,
                "cloned_from": item.spec.donor_part,
                "cloned_from_key": item.spec.extra_marker.get("donorKey", ""),
                "master_part": item.spec.master_part,
                "picture_idx": item.spec.picture_idx,
                "geometry_emu": dict(item.spec.picture_rect),
                "removed_placeholders": list(item.removed_placeholders),
                "relationship_id": item.rel_id,
                "layout_id": item.layout_id,
                "rationale": item.spec.rationale,
            }
        )
    records.sort(key=lambda record: record["key"])
    return records


def _initial_report(
    source: Path, source_sha: str, margin_emu: int, gaps: dict[str, Any]
) -> dict[str, Any]:
    return {
        "kind": "office_template_normalization",
        "version": MANIFEST_VERSION,
        "source_file": source.name,
        "source_sha256": source_sha,
        "template_margin_emu": margin_emu,
        "required_shapes": gaps["required_shapes"],
        "covered_by_template": gaps["covered"],
        "generated_layouts": [],
        "warnings": [
            f"no layout of this template can host {shape!r}: every candidate either "
            "has no legible title without the picture behind it, or its safe area is "
            "too small"
            for shape in gaps["unsatisfiable"]
        ],
    }


def _write_manifest(report: dict[str, Any], output: Path, manifest_path: str | Path | None) -> Path:
    manifest = Path(manifest_path) if manifest_path is not None else output.parent / MANIFEST_NAME
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {**report, "generated_at": datetime.now(UTC).isoformat(timespec="seconds")},
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def normalize_template(
    source_path: str | Path,
    output_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Write a derivative of ``source_path`` that covers the required shapes."""
    source = Path(source_path)
    if not source.is_file():
        raise NormalizationError(f"template not found: {source}")
    output = Path(output_path)

    snapshot = build_template_snapshot(source)
    margin_emu = template_margin_emu(snapshot.get("layouts", []))
    gaps = analyse_gaps(snapshot, margin_emu)
    source_sha = _sha256(source)
    report = _initial_report(source, source_sha, margin_emu, gaps)

    specs: list[LayoutSpec] = gaps["specs"]
    if not specs:
        report["status"] = "unchanged"
        report["output_path"] = None
        report["manifest_path"] = None
        return report

    generated = add_layouts(source, output, specs)
    derived_snapshot = build_template_snapshot(output)
    report["status"] = "normalized"
    report["output_path"] = str(output)
    report["generated_layouts"] = _derived_records(generated, derived_snapshot)
    report["layout_count_before"] = len(snapshot.get("layouts", []))
    report["layout_count_after"] = len(derived_snapshot.get("layouts", []))

    manifest = _write_manifest(report, output, manifest_path)
    report["manifest_path"] = str(manifest)
    return report


__all__ = [
    "MANIFEST_NAME",
    "NormalizationError",
    "normalize_template",
]
