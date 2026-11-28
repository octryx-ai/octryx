"""The normalised template as a profile artefact."""


from __future__ import annotations

from pathlib import Path
from typing import Any

from ..office_identity.template_normalization import normalize_template
from .normalized_template_manifest import (
    NORMALIZATION_MANIFEST_NAME,
    NORMALIZED_TEMPLATE_NAME,
    PRESENTATION_SUFFIXES,
    STATUS_FAILED,
    STATUS_UNCHANGED,
    _customization,
    _envelope,
    _failure,
    _is_current,
    _keep_customized,
    _sha256,
    _snapshot_of,
    _UnusableSourceError,
    _write_json,
    read_normalization_manifest,
)


def _source_digest(source: Path, root: Path) -> tuple[str, dict[str, Any] | None]:
    try:
        if not source.is_file():
            raise _UnusableSourceError("template_source_not_found")
        if source.suffix.lower() not in PRESENTATION_SUFFIXES:
            raise _UnusableSourceError("template_source_not_presentation")
        return _sha256(source), None
    except (_UnusableSourceError, OSError) as error:
        code = error.code if isinstance(error, _UnusableSourceError) else "template_source_unreadable"
        result = _envelope(
            status=STATUS_FAILED,
            source=source,
            source_sha="",
            error=_failure(code, error),
        )
        _write_json(root / NORMALIZATION_MANIFEST_NAME, result)
        return "", result


def _rebuild(source: Path, root: Path, derivative: Path, source_sha: str) -> dict[str, Any]:
    if derivative.exists():
        derivative.unlink()
    try:
        report = normalize_template(
            source, derivative, manifest_path=root / NORMALIZATION_MANIFEST_NAME
        )
        template = derivative if derivative.is_file() else source
        snapshot = _snapshot_of(template, root)
    except Exception as error:  # noqa: BLE001 - a broken template must not fail the upload
        if derivative.exists():
            derivative.unlink()
        result = _envelope(
            status=STATUS_FAILED,
            source=source,
            source_sha=source_sha,
            error=_failure("template_normalization_failed", error),
            warnings=["normalization failed; the original template stays in use"],
        )
    else:
        result = _envelope(
            status=str(report.get("status") or STATUS_UNCHANGED),
            source=source,
            source_sha=source_sha,
            derivative_sha=_sha256(derivative) if derivative.is_file() else None,
            snapshot=snapshot,
            report=report,
        )
    _write_json(root / NORMALIZATION_MANIFEST_NAME, result)
    return result


def build_profile_normalization(
    source_path: str | Path,
    profile_root: str | Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    source = Path(source_path).expanduser()
    root = Path(profile_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    derivative = root / NORMALIZED_TEMPLATE_NAME

    source_sha, failed = _source_digest(source, root)
    if failed is not None:
        return failed

    manifest = read_normalization_manifest(root)
    exists, customized = _customization(manifest, derivative)
    if customized and not force:
        return _keep_customized(root, source, source_sha, manifest)
    if not force and _is_current(manifest, root, source_sha, exists):
        return {**manifest, "reused": True}
    return _rebuild(source, root, derivative, source_sha)


__all__ = [
    "build_profile_normalization",
]
