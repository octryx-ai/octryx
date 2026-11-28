"""Which template file a profile consumer opens, and the registry fields for a normalisation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .normalized_template_manifest import (
    MAX_WARNINGS,
    NORMALIZATION_MANIFEST_NAME,
    NORMALIZED_TEMPLATE_NAME,
    ORIGIN_NORMALIZED,
    ORIGIN_ORIGINAL,
    STATUS_FAILED,
    STATUS_NORMALIZED,
    _customization,
    _sha256,
    read_normalization_manifest,
)


@dataclass(frozen=True)
class ResolvedTemplate:
    path: Path
    origin: str
    status: str
    customized: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "origin": self.origin,
            "status": self.status,
            "customized": self.customized,
            "reason": self.reason,
        }



def resolve_profile_template_path(
    profile_root: str | Path, source_path: str | Path
) -> ResolvedTemplate:
    root = Path(profile_root).expanduser()
    source = Path(source_path).expanduser()
    derivative = root / NORMALIZED_TEMPLATE_NAME
    manifest = read_normalization_manifest(root)
    status = str(manifest.get("status") or "")

    _exists, customized = _customization(manifest, derivative)
    if customized:
        return ResolvedTemplate(
            path=derivative,
            origin=ORIGIN_NORMALIZED,
            status=status or STATUS_NORMALIZED,
            customized=True,
            reason="normalized.potx was edited after generation; the customer's version wins",
        )
    if not derivative.is_file():
        return ResolvedTemplate(
            path=source,
            origin=ORIGIN_ORIGINAL,
            status=status or "missing",
            customized=False,
            reason=(
                "no derivative exists for this profile"
                if status != STATUS_FAILED
                else "normalization failed; the original is the template of record"
            ),
        )
    if not source.is_file():
        return ResolvedTemplate(
            path=derivative,
            origin=ORIGIN_NORMALIZED,
            status=status or STATUS_NORMALIZED,
            customized=False,
            reason="the original is missing; the derivative is the only template left",
        )
    if str(manifest.get("source_sha256") or "") != _sha256(source):
        return ResolvedTemplate(
            path=source,
            origin=ORIGIN_ORIGINAL,
            status="stale",
            customized=False,
            reason="the original changed after normalization; re-normalize to use a derivative",
        )
    return ResolvedTemplate(
        path=derivative,
        origin=ORIGIN_NORMALIZED,
        status=STATUS_NORMALIZED,
        customized=False,
        reason="the derivative was generated from this exact original",
    )


def resolve_template_for_profile(profile: dict[str, Any]) -> ResolvedTemplate:
    return resolve_profile_template_path(
        str(profile.get("profile_root") or ""), str(profile.get("source_path") or "")
    )


def normalization_record_fields(
    profile_root: str | Path, result: dict[str, Any]
) -> dict[str, Any]:
    root = Path(profile_root).expanduser()
    normalized_rel = result.get("normalized_path")
    snapshot_rel = result.get("snapshot_path")
    return {
        "normalization_status": str(result.get("status") or ""),
        "normalization_manifest_path": str((root / NORMALIZATION_MANIFEST_NAME).resolve()),
        "normalized_template_path": (
            str((root / str(normalized_rel)).resolve()) if normalized_rel else ""
        ),
        "template_snapshot_path": (
            str((root / str(snapshot_rel)).resolve()) if snapshot_rel else ""
        ),
        "normalization_summary": {
            "status": str(result.get("status") or ""),
            "customized": bool(result.get("customized")),
            "derived_layout_keys": list(result.get("derived_layout_keys") or []),
            "error": result.get("error"),
            "warnings": list(result.get("warnings") or [])[:MAX_WARNINGS],
        },
    }
