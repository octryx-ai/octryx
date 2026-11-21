"""The upload path produces, survives and refreshes the normalisation artefacts, and the synthetic corporate template normalises through the profile path."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import corp_identity_service as svc
from app.services.corp_identity.normalized_template import build_profile_normalization
from app.services.corp_identity.normalized_template_manifest import (
    NORMALIZATION_MANIFEST_NAME,
    NORMALIZED_TEMPLATE_NAME,
    STATUS_FAILED,
    STATUS_NORMALIZED,
    TEMPLATE_SNAPSHOT_NAME,
    read_normalization_manifest,
)
from app.services.corp_identity.normalized_template_resolve import resolve_profile_template_path
from app.services.corp_identity_service import (
    get_corp_identity_profile_detail,
    reextract_corp_identity_profile,
    save_uploaded_corp_identity_profile,
)
from tests.corp_identity_normalized_template_support import (  # noqa: F401
    DERIVED_KEY,
    _default_template,
    _variant_template,
    profile_root,
)
from tests.office_template_fixture import write_template

# ---------------------------------------------------------------------------
# the upload path
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_corp_root(tmp_path, monkeypatch):
    """Give these uploads their own profile root.

    Profile cleanup prunes every directory under the profile root that the
    current registry does not reference. Under xdist that makes the shared
    ``uploads/corp-identities`` directory a race between suites — a pre-existing
    hazard these tests neither inherit nor add to once their profiles live
    somewhere of their own.
    """
    root = tmp_path / "corp-identities"
    root.mkdir()
    monkeypatch.setattr(svc, "CORP_IDENTITY_ROOT", root)
    return root


@pytest.mark.asyncio
async def test_upload_produces_the_normalization_artifacts(db, tmp_path, isolated_corp_root):
    template = _default_template(tmp_path / "brand.pptx", tag="upload-artifacts")

    profile = await save_uploaded_corp_identity_profile(
        db, file_name=template.name, file_bytes=template.read_bytes()
    )
    root = Path(profile["profile_root"])

    assert profile["normalization_status"] == STATUS_NORMALIZED
    assert sorted(
        name
        for name in (NORMALIZED_TEMPLATE_NAME, NORMALIZATION_MANIFEST_NAME, TEMPLATE_SNAPSHOT_NAME)
        if (root / name).is_file()
    ) == sorted((NORMALIZED_TEMPLATE_NAME, NORMALIZATION_MANIFEST_NAME, TEMPLATE_SNAPSHOT_NAME))
    assert profile["normalization_summary"]["derived_layout_keys"] == [DERIVED_KEY]

    detail = await get_corp_identity_profile_detail(db, profile["id"])
    assert detail["normalization"]["status"] == STATUS_NORMALIZED

    composer_template = svc.resolve_corp_identity_composer_template(detail)
    assert composer_template.path == root / NORMALIZED_TEMPLATE_NAME
    assert composer_template.origin == "normalized"

    # additive: the established artefacts are untouched
    for name in ("brand-profile.json", "layout-catalog.json", "icon-catalog.json", "llm-guide.md"):
        assert (root / name).is_file()


@pytest.mark.asyncio
async def test_upload_survives_a_failing_normalization(db, tmp_path, isolated_corp_root, monkeypatch):
    """Normalisation is never allowed to fail the upload.

    The failure is injected rather than staged with a corrupt file: a package
    broken enough to defeat normalisation is already rejected by the existing
    extraction step, so it would never reach this code. What has to be proven is
    the discipline — profile valid, status recorded, original in use.
    """
    monkeypatch.setattr(
        "app.services.corp_identity.normalized_template.normalize_template",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no master in template")),
    )
    template = _default_template(tmp_path / "brand.pptx", tag="upload-failure")

    profile = await save_uploaded_corp_identity_profile(
        db, file_name=template.name, file_bytes=template.read_bytes()
    )
    root = Path(profile["profile_root"])

    assert profile["normalization_status"] == STATUS_FAILED
    assert profile["normalization_summary"]["error"] == {
        "type": "RuntimeError",
        "error_code": "template_normalization_failed",
    }
    assert not (root / NORMALIZED_TEMPLATE_NAME).exists()
    assert (root / "brand-profile.json").is_file()
    assert (root / "llm-guide.md").is_file()

    resolved = resolve_profile_template_path(root, Path(profile["source_path"]))
    assert resolved.path == Path(profile["source_path"])
    assert resolved.origin == "original"


@pytest.mark.asyncio
async def test_reextract_refreshes_the_normalization_artifacts(db, tmp_path, isolated_corp_root):
    template = _default_template(tmp_path / "brand.pptx", tag="upload-reextract")
    profile = await save_uploaded_corp_identity_profile(
        db, file_name=template.name, file_bytes=template.read_bytes()
    )
    root = Path(profile["profile_root"])
    first = read_normalization_manifest(root)

    refreshed = await reextract_corp_identity_profile(db, profile["id"])

    assert refreshed["normalization_status"] == STATUS_NORMALIZED
    assert read_normalization_manifest(root)["normalized_sha256"] == first["normalized_sha256"]


@pytest.mark.asyncio
async def test_customized_derivative_is_not_a_cleanup_target(db, tmp_path, isolated_corp_root):
    template = _default_template(tmp_path / "brand.pptx", tag="upload-customized")
    profile = await save_uploaded_corp_identity_profile(
        db, file_name=template.name, file_bytes=template.read_bytes()
    )
    root = Path(profile["profile_root"])
    derivative = root / NORMALIZED_TEMPLATE_NAME

    generated = await get_corp_identity_profile_detail(db, profile["id"])
    assert str(derivative.resolve()) in generated["storage_lifecycle"]["safe_cleanup_paths"]

    _variant_template(derivative)
    build_profile_normalization(Path(profile["source_path"]), root)
    customized = await get_corp_identity_profile_detail(db, profile["id"])

    assert str(derivative.resolve()) not in customized["storage_lifecycle"]["safe_cleanup_paths"]
    assert any(
        entry["kind"] == "customized_template"
        for entry in customized["storage_lifecycle"]["retained_companions"]
    )


# ---------------------------------------------------------------------------
# corporate template
# ---------------------------------------------------------------------------


def test_corporate_template_normalizes_through_the_profile_path(profile_root, tmp_path):  # noqa: F811
    template = write_template(tmp_path / "corporate.potx", "brand")

    result = build_profile_normalization(template, profile_root)

    assert result["status"] == STATUS_NORMALIZED
    assert result["derived_layout_keys"] == [DERIVED_KEY]
    assert resolve_profile_template_path(profile_root, template).origin == "normalized"
