"""Manifest, digest and snapshot helpers behind the normalised profile template."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..error_facts import error_code, error_type
from ..office_identity.template_snapshot import build_template_snapshot

NORMALIZED_TEMPLATE_NAME = "normalized.potx"
NORMALIZATION_MANIFEST_NAME = "normalization.json"
TEMPLATE_SNAPSHOT_NAME = "template-snapshot.json"

MANIFEST_KIND = "corp_identity_template_normalization"
MANIFEST_VERSION = 1

STATUS_NORMALIZED = "normalized"
STATUS_UNCHANGED = "unchanged"
STATUS_FAILED = "failed"

ORIGIN_NORMALIZED = "normalized"
ORIGIN_ORIGINAL = "original"

PRESENTATION_SUFFIXES = {".potx", ".pptx"}

#: Bounds, in the spirit of the surrounding profile code: the manifest is a
#: report, not a data dump. Both lists are already short in practice (one
#: generated layout, a handful of warnings); the caps make that structural.
MAX_GENERATED_LAYOUTS = 20
MAX_WARNINGS = 20
MAX_MESSAGE_CHARS = 800


class _UnusableSourceError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _failure(code: str, error: BaseException) -> dict[str, str]:
    return {"type": error_type(error), "error_code": error_code(code)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_normalization_manifest(profile_root: str | Path) -> dict[str, Any]:
    path = Path(profile_root).expanduser() / NORMALIZATION_MANIFEST_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _customization(manifest: dict[str, Any], derivative: Path) -> tuple[bool, bool]:
    if not derivative.is_file():
        return False, False
    recorded = str(manifest.get("normalized_sha256") or "").strip()
    if not recorded:
        return True, True
    return True, _sha256(derivative) != recorded


def _envelope(
    *,
    status: str,
    source: Path,
    source_sha: str,
    customized: bool = False,
    derivative_sha: str | None = None,
    snapshot: dict[str, Any] | None = None,
    report: dict[str, Any] | None = None,
    error: dict[str, str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    report = report or {}
    layouts = list(report.get("generated_layouts") or [])[:MAX_GENERATED_LAYOUTS]
    all_warnings = [*(report.get("warnings") or []), *(warnings or [])]
    derived_keys = sorted(
        str(layout.get("key") or "")
        for layout in (snapshot or {}).get("layouts", [])
        if str(layout.get("origin") or "") == "derived"
    )
    return {
        "kind": MANIFEST_KIND,
        "version": MANIFEST_VERSION,
        "status": status,
        "customized": customized,
        "source_file": source.name,
        "source_sha256": source_sha,
        "normalized_path": NORMALIZED_TEMPLATE_NAME if derivative_sha else None,
        "normalized_sha256": derivative_sha,
        "snapshot_path": TEMPLATE_SNAPSHOT_NAME if snapshot is not None else None,
        "snapshot_layout_count": len(snapshot.get("layouts", [])) if snapshot else 0,
        "derived_layout_keys": derived_keys,
        "template_margin_emu": report.get("template_margin_emu"),
        "required_shapes": list(report.get("required_shapes") or []),
        "covered_by_template": dict(report.get("covered_by_template") or {}),
        "generated_layouts": layouts,
        "warnings": [str(item)[:MAX_MESSAGE_CHARS] for item in all_warnings][:MAX_WARNINGS],
        "error": error,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }


def _snapshot_of(template: Path, profile_root: Path) -> dict[str, Any]:
    snapshot = build_template_snapshot(template)
    _write_json(profile_root / TEMPLATE_SNAPSHOT_NAME, snapshot)
    return snapshot


def _keep_customized(
    profile_root: Path, source: Path, source_sha: str, manifest: dict[str, Any]
) -> dict[str, Any]:
    derivative = profile_root / NORMALIZED_TEMPLATE_NAME
    warnings = [
        "normalized.potx was edited after it was generated; it is kept as-is and "
        "used as the profile template"
    ]
    if str(manifest.get("source_sha256") or "") != source_sha:
        warnings.append(
            "the original template changed, but re-normalization was skipped to "
            "preserve those edits; re-normalize explicitly to discard them"
        )
    #: The digest of *our* output stays recorded, never the edited one — it is
    #: the only evidence that lets the next run recognise the edit again. The
    #: customer's current digest is carried separately, for transparency.
    generated_sha = str(manifest.get("normalized_sha256") or "") or None
    try:
        snapshot = _snapshot_of(derivative, profile_root)
    except Exception as error:  # noqa: BLE001 - any parse failure is a manifest state
        result = _envelope(
            status=STATUS_FAILED,
            source=source,
            source_sha=source_sha,
            customized=True,
            derivative_sha=generated_sha,
            error=_failure("customized_template_unreadable", error),
            warnings=warnings,
        )
    else:
        result = _envelope(
            status=str(manifest.get("status") or STATUS_NORMALIZED),
            source=source,
            source_sha=source_sha,
            customized=True,
            derivative_sha=generated_sha,
            snapshot=snapshot,
            warnings=warnings,
        )
    result["normalized_path"] = NORMALIZED_TEMPLATE_NAME
    result["customized_sha256"] = _sha256(derivative)
    _write_json(profile_root / NORMALIZATION_MANIFEST_NAME, result)
    return result


def _is_current(manifest: dict[str, Any], profile_root: Path, source_sha: str, exists: bool) -> bool:
    if str(manifest.get("source_sha256") or "") != source_sha:
        return False
    if not (profile_root / TEMPLATE_SNAPSHOT_NAME).is_file():
        return False
    status = str(manifest.get("status") or "")
    if status == STATUS_NORMALIZED:
        return exists
    return status == STATUS_UNCHANGED and not exists
