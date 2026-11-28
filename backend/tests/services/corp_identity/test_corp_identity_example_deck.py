"""A profile's example deck: attached only when it shares layout names with the profile's template, at most one,
and clearable."""

from pathlib import Path

import pytest

from app.services import corp_identity_service as svc
from tests.services.office_identity.test_office_identity_example_usage import (
    BRAND_LAYOUTS,
    EXAMPLE_LAYOUT,
    _build_brand_template,
    _build_example_deck,
)


async def _seed_presentation_profile(db, tmp_path) -> str:
    profile_root = tmp_path / "profile-root"
    (profile_root / "source").mkdir(parents=True)
    brand = profile_root / "source" / "brand.potx"
    _build_brand_template(brand, BRAND_LAYOUTS)
    record = {
        "id": "profile-1",
        "name": "Brand",
        "source_path": str(brand.resolve()),
        "profile_root": str(profile_root.resolve()),
    }
    await svc._save_registry(db, [record])
    return "profile-1"


@pytest.mark.asyncio
async def test_attach_valid_example_sets_path(db, tmp_path, monkeypatch):
    profile_id = await _seed_presentation_profile(db, tmp_path)

    async def _detail(db_, pid):
        return next(r for r in await svc._load_registry(db_) if r["id"] == pid)

    monkeypatch.setattr(svc, "get_corp_identity_profile_detail", _detail)

    example = tmp_path / "example.pptx"
    _build_example_deck(example, layout_name=EXAMPLE_LAYOUT, slide_count=3)

    detail = await svc.attach_example_deck_to_corp_identity_profile(
        db, profile_id=profile_id, file_name="example.pptx", file_bytes=example.read_bytes()
    )

    assert detail["example_deck_path"]
    assert Path(detail["example_deck_path"]).is_file()
    assert detail["example_deck_file"] == "example.pptx"
    assert detail["example_deck_layouts_learned"] >= 1


@pytest.mark.asyncio
async def test_attach_mismatched_example_is_rejected_and_keeps_prior(db, tmp_path, monkeypatch):
    profile_id = await _seed_presentation_profile(db, tmp_path)

    async def _detail(db_, pid):
        return next(r for r in await svc._load_registry(db_) if r["id"] == pid)

    monkeypatch.setattr(svc, "get_corp_identity_profile_detail", _detail)

    good = tmp_path / "good.pptx"
    _build_example_deck(good, layout_name=EXAMPLE_LAYOUT, slide_count=3)
    await svc.attach_example_deck_to_corp_identity_profile(
        db, profile_id=profile_id, file_name="good.pptx", file_bytes=good.read_bytes()
    )

    bad = tmp_path / "bad.pptx"
    _build_example_deck(bad, layout_name="A Layout The Brand Lacks", slide_count=2)
    with pytest.raises(ValueError, match="teaches nothing"):
        await svc.attach_example_deck_to_corp_identity_profile(
            db, profile_id=profile_id, file_name="bad.pptx", file_bytes=bad.read_bytes()
        )

    record = next(r for r in await svc._load_registry(db) if r["id"] == profile_id)
    assert Path(record["example_deck_path"]).name == "good.pptx"


@pytest.mark.asyncio
async def test_non_pptx_example_is_rejected(db, tmp_path, monkeypatch):
    profile_id = await _seed_presentation_profile(db, tmp_path)
    with pytest.raises(ValueError, match="must be a .pptx or .potx"):
        await svc.attach_example_deck_to_corp_identity_profile(
            db, profile_id=profile_id, file_name="notes.txt", file_bytes=b"hello"
        )


@pytest.mark.asyncio
async def test_clear_removes_example(db, tmp_path, monkeypatch):
    profile_id = await _seed_presentation_profile(db, tmp_path)

    async def _detail(db_, pid):
        return next(r for r in await svc._load_registry(db_) if r["id"] == pid)

    monkeypatch.setattr(svc, "get_corp_identity_profile_detail", _detail)

    example = tmp_path / "example.pptx"
    _build_example_deck(example, layout_name=EXAMPLE_LAYOUT, slide_count=3)
    await svc.attach_example_deck_to_corp_identity_profile(
        db, profile_id=profile_id, file_name="example.pptx", file_bytes=example.read_bytes()
    )

    detail = await svc.clear_example_deck_from_corp_identity_profile(db, profile_id=profile_id)

    assert "example_deck_path" not in detail
    assert "example_deck_file" not in detail
