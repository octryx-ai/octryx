"""A customer edit of the derivative is never overwritten and only a forced rebuild discards it, and a broken or missing template fails explicitly while keeping the original."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from app.services.corp_identity.normalized_template import build_profile_normalization
from app.services.corp_identity.normalized_template_manifest import (
    NORMALIZATION_MANIFEST_NAME,
    NORMALIZED_TEMPLATE_NAME,
    STATUS_FAILED,
    STATUS_NORMALIZED,
    TEMPLATE_SNAPSHOT_NAME,
)
from app.services.corp_identity.normalized_template_resolve import resolve_profile_template_path
from tests.corp_identity_normalized_template_support import (  # noqa: F401
    _default_template,
    _variant_template,
    profile_root,
    source,
)


def _broken_template(path: Path) -> Path:
    """A zip that is not a presentation package: normalisation cannot succeed."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("not-a-presentation.txt", "broken")
    return path


# ---------------------------------------------------------------------------
# case 4 — the customer edited the derivative
# ---------------------------------------------------------------------------


def test_customized_derivative_is_never_overwritten(profile_root, source):  # noqa: F811
    build_profile_normalization(source, profile_root)
    derivative = profile_root / NORMALIZED_TEMPLATE_NAME
    _variant_template(derivative)
    edited = derivative.read_bytes()

    result = build_profile_normalization(source, profile_root)

    assert result["customized"] is True
    assert derivative.read_bytes() == edited
    assert any("edited after it was generated" in warning for warning in result["warnings"])

    # The verdict has to survive repetition: the manifest keeps the digest of
    # *our* output, so the edit is still recognisable on every later run.
    again = build_profile_normalization(source, profile_root)
    assert again["customized"] is True
    assert derivative.read_bytes() == edited
    assert resolve_profile_template_path(profile_root, source).customized is True


def test_customized_derivative_wins_over_a_changed_original(profile_root, source):  # noqa: F811
    build_profile_normalization(source, profile_root)
    derivative = profile_root / NORMALIZED_TEMPLATE_NAME
    _variant_template(derivative)
    edited = derivative.read_bytes()
    _variant_template(source)

    result = build_profile_normalization(source, profile_root)
    resolved = resolve_profile_template_path(profile_root, source)

    assert result["customized"] is True
    assert any("re-normalization was skipped" in warning for warning in result["warnings"])
    assert derivative.read_bytes() == edited
    assert resolved.path == derivative
    assert resolved.customized is True


def test_forced_rebuild_is_the_explicit_way_to_discard_an_edit(profile_root, source):  # noqa: F811
    first = build_profile_normalization(source, profile_root)
    derivative = profile_root / NORMALIZED_TEMPLATE_NAME
    _variant_template(derivative)

    result = build_profile_normalization(source, profile_root, force=True)

    assert result["customized"] is False
    assert result["normalized_sha256"] == first["normalized_sha256"]


def test_snapshot_follows_the_customized_derivative(profile_root, source):  # noqa: F811
    build_profile_normalization(source, profile_root)
    derivative = profile_root / NORMALIZED_TEMPLATE_NAME
    _variant_template(derivative)

    build_profile_normalization(source, profile_root)
    snapshot = json.loads((profile_root / TEMPLATE_SNAPSHOT_NAME).read_text(encoding="utf-8"))

    # The customer's file has no generated layout any more — the snapshot says so
    # instead of describing a file that is no longer on disk.
    assert [layout for layout in snapshot["layouts"] if layout.get("origin") == "derived"] == []


# ---------------------------------------------------------------------------
# case 5 — a broken template
# ---------------------------------------------------------------------------


def test_broken_template_fails_explicitly_and_keeps_the_original(profile_root, tmp_path):  # noqa: F811
    broken = _broken_template(tmp_path / "broken.pptx")

    result = build_profile_normalization(broken, profile_root)
    resolved = resolve_profile_template_path(profile_root, broken)

    assert result["status"] == STATUS_FAILED
    assert result["error"]["error_code"] == "template_normalization_failed"
    assert "message" not in result["error"]
    assert not (profile_root / NORMALIZED_TEMPLATE_NAME).exists()
    assert (profile_root / NORMALIZATION_MANIFEST_NAME).is_file()
    assert resolved.path == broken
    assert resolved.origin == "original"
    assert resolved.status == STATUS_FAILED


def test_missing_source_fails_explicitly(profile_root, tmp_path):  # noqa: F811
    result = build_profile_normalization(tmp_path / "gone.pptx", profile_root)

    assert result["status"] == STATUS_FAILED
    assert result["error"]["error_code"] == "template_source_not_found"


def test_failed_normalization_is_retried_rather_than_frozen(profile_root, tmp_path):  # noqa: F811
    path = _broken_template(tmp_path / "template.pptx")
    assert build_profile_normalization(path, profile_root)["status"] == STATUS_FAILED

    path.unlink()
    _default_template(path)
    assert build_profile_normalization(path, profile_root)["status"] == STATUS_NORMALIZED


def test_resolution_without_any_manifest_returns_the_original(profile_root, source):  # noqa: F811
    resolved = resolve_profile_template_path(profile_root, source)

    assert resolved.path == source
    assert resolved.origin == "original"
    assert resolved.status == "missing"


def test_untracked_derivative_counts_as_the_customers_file(profile_root, source):  # noqa: F811
    (profile_root / NORMALIZED_TEMPLATE_NAME).write_bytes(b"someone put this here")

    resolved = resolve_profile_template_path(profile_root, source)

    assert resolved.customized is True
    assert resolved.path == profile_root / NORMALIZED_TEMPLATE_NAME
