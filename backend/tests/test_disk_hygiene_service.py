from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.models import SystemConfig
from app.services.disk_hygiene import collect_backend_disk_hygiene_plan, run_backend_disk_hygiene


def _set_mtime_hours_ago(path: Path, *, hours: int) -> None:
    timestamp = (datetime.now(tz=UTC) - timedelta(hours=hours)).timestamp()
    os.utime(path, (timestamp, timestamp))


@pytest.mark.asyncio
async def test_disk_hygiene_plan_detects_rebuildable_corp_identity_cache_only(db, tmp_path):
    corp_root = tmp_path / "corp-identities"
    profile_root = corp_root / "profile-a"
    source_dir = profile_root / "source"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "brand.potx"
    source_path.write_text("pptx", encoding="utf-8")
    extracted_dir = profile_root / "_extracted"
    extracted_dir.mkdir(parents=True)
    (extracted_dir / "slide.xml").write_text("stub", encoding="utf-8")
    companion_dir = profile_root / "ai-template"
    companion_dir.mkdir(parents=True)
    companion_path = companion_dir / "corp-brand.dotx"
    companion_path.write_text("keep", encoding="utf-8")
    _set_mtime_hours_ago(extracted_dir, hours=72)

    db.add(
        SystemConfig(
            key="agent.corp_identity_registry",
            value=json.dumps(
                [
                    {
                        "id": "profile-a",
                        "name": "Profile A",
                        "profile_root": str(profile_root),
                        "source_path": str(source_path),
                        "ai_template_path": str(companion_dir / "brand-ai.potx"),
                    }
                ]
            ),
        )
    )
    await db.commit()

    plan = await collect_backend_disk_hygiene_plan(
        db,
        corp_identity_root=corp_root,
        office_import_root=tmp_path / "office-imports",
        corp_identity_cache_min_age_hours=24,
        office_import_stale_min_age_hours=24,
    )

    assert plan["totals"]["count"] == 1
    candidate = plan["candidates"][0]
    assert candidate["kind"] == "corp_identity_extracted_cache"
    assert candidate["path"] == str(extracted_dir.resolve())
    assert Path(candidate["metadata"]["source_path"]) == source_path.resolve()
    assert companion_path.exists()


@pytest.mark.asyncio
async def test_disk_hygiene_plan_reports_bounded_cleanup_scope(db, tmp_path):
    plan = await collect_backend_disk_hygiene_plan(
        db,
        corp_identity_root=tmp_path / "corp-identities",
        office_import_root=tmp_path / "office-imports",
        include_corp_identity_candidates=True,
        include_office_import_candidates=True,
    )

    assert plan["policy"]["cleanup_scope"] == [
        "corp_identity_extracted_cache",
        "office_template_import_package",
    ]
    assert "Only rebuildable corp-identity extraction caches" in plan["policy"]["safety_note"]


@pytest.mark.asyncio
async def test_disk_hygiene_plan_skips_referenced_office_import_package(db, tmp_path):
    import_root = tmp_path / "office-imports"
    import_root.mkdir(parents=True)
    active_package = import_root / "active"
    stale_package = import_root / "stale"
    for package_root in (active_package, stale_package):
        (package_root / "ai-template").mkdir(parents=True)
        (package_root / "manifest.json").write_text("{}", encoding="utf-8")
        ((package_root / "ai-template") / "deck-ai.potx").write_text("stub", encoding="utf-8")
        _set_mtime_hours_ago(package_root, hours=96)

    db.add(
        SystemConfig(
            key="agent.office_template_library",
            value=json.dumps(
                [
                    {
                        "key": "active-deck",
                        "name": "Active Deck",
                        "doc_type": "pptx",
                        "path": str((active_package / "ai-template" / "deck-ai.potx").resolve()),
                        "is_default": True,
                        "storage_contract": {
                            "doc_type": "pptx",
                            "storage_kind": "uploaded_source_with_generated_ai_template",
                            "source_path": str((tmp_path / "uploads" / "deck.potx").resolve()),
                            "active_template_path": str((active_package / "ai-template" / "deck-ai.potx").resolve()),
                            "package_root": str(active_package.resolve()),
                            "generated_artifact_root": str((active_package / "ai-template").resolve()),
                            "package_manifest_path": str((active_package / "manifest.json").resolve()),
                            "ai_template_path": str((active_package / "ai-template" / "deck-ai.potx").resolve()),
                            "has_import_package": True,
                            "has_generated_ai_artifact": True,
                        },
                    }
                ]
            ),
        )
    )
    await db.commit()

    plan = await collect_backend_disk_hygiene_plan(
        db,
        corp_identity_root=tmp_path / "corp-identities",
        office_import_root=import_root,
        corp_identity_cache_min_age_hours=24,
        office_import_stale_min_age_hours=48,
    )

    assert plan["totals"]["count"] == 1
    candidate = plan["candidates"][0]
    assert candidate["kind"] == "office_template_import_package"
    assert candidate["path"] == str(stale_package.resolve())
    assert active_package.exists()


@pytest.mark.asyncio
async def test_run_backend_disk_hygiene_dry_run_preserves_files(db, tmp_path):
    import_root = tmp_path / "office-imports"
    package_root = import_root / "stale"
    package_root.mkdir(parents=True)
    (package_root / "manifest.json").write_text("{}", encoding="utf-8")
    _set_mtime_hours_ago(package_root, hours=96)

    result = await run_backend_disk_hygiene(
        db,
        dry_run=True,
        corp_identity_root=tmp_path / "corp-identities",
        office_import_root=import_root,
        corp_identity_cache_min_age_hours=24,
        office_import_stale_min_age_hours=48,
    )

    assert result["totals"]["count"] == 1
    assert result["deleted"] == []
    assert package_root.exists()


@pytest.mark.asyncio
async def test_run_backend_disk_hygiene_deletes_safe_candidates(db, tmp_path):
    import_root = tmp_path / "office-imports"
    package_root = import_root / "stale"
    package_root.mkdir(parents=True)
    (package_root / "manifest.json").write_text("{}", encoding="utf-8")
    _set_mtime_hours_ago(package_root, hours=96)

    result = await run_backend_disk_hygiene(
        db,
        dry_run=False,
        corp_identity_root=tmp_path / "corp-identities",
        office_import_root=import_root,
        corp_identity_cache_min_age_hours=24,
        office_import_stale_min_age_hours=48,
    )

    assert result["deleted_count"] == 1
    assert result["deleted"][0]["path"] == str(package_root.resolve())
    assert not package_root.exists()


@pytest.mark.asyncio
async def test_disk_hygiene_plan_uses_db_backed_retention_defaults_when_thresholds_are_omitted(db, tmp_path):
    import_root = tmp_path / "office-imports"
    package_root = import_root / "stale"
    package_root.mkdir(parents=True)
    (package_root / "manifest.json").write_text("{}", encoding="utf-8")
    _set_mtime_hours_ago(package_root, hours=30)

    db.add(SystemConfig(key="agent.disk_hygiene.office_import_stale_min_age_hours", value="24"))
    await db.commit()

    plan = await collect_backend_disk_hygiene_plan(
        db,
        corp_identity_root=tmp_path / "corp-identities",
        office_import_root=import_root,
    )

    assert plan["totals"]["count"] == 1
    assert plan["policy"]["office_import_stale_min_age_hours"] == 24
    assert plan["candidates"][0]["path"] == str(package_root.resolve())


@pytest.mark.asyncio
async def test_disk_hygiene_plan_prefers_explicit_thresholds_over_db_backed_defaults(db, tmp_path):
    import_root = tmp_path / "office-imports"
    package_root = import_root / "stale"
    package_root.mkdir(parents=True)
    (package_root / "manifest.json").write_text("{}", encoding="utf-8")
    _set_mtime_hours_ago(package_root, hours=30)

    db.add(SystemConfig(key="agent.disk_hygiene.office_import_stale_min_age_hours", value="24"))
    await db.commit()

    plan = await collect_backend_disk_hygiene_plan(
        db,
        corp_identity_root=tmp_path / "corp-identities",
        office_import_root=import_root,
        office_import_stale_min_age_hours=48,
    )

    assert plan["totals"]["count"] == 0
    assert plan["policy"]["office_import_stale_min_age_hours"] == 48
