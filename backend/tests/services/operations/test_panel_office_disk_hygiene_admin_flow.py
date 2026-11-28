from __future__ import annotations

import pytest

from app.services import disk_hygiene as disk_hygiene_service

SAFETY_NOTE = "Only rebuildable corp-identity extraction caches and unreferenced Office import packages are eligible."


@pytest.mark.asyncio
async def test_panel_office_disk_hygiene_preview_uses_bounded_scope(
    client,
    auth_headers,
    monkeypatch,
):
    calls: list[dict[str, object]] = []

    async def fake_collect_backend_disk_hygiene_plan(*args: object, **kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        return {
            "generated_at": "2026-04-21T00:00:00+00:00",
            "candidates": [],
            "totals": {"count": 0, "bytes_used": 0, "bytes_used_mb": 0.0, "by_kind": {}},
            "policy": {
                "corp_identity_cache_min_age_hours": 24,
                "office_import_stale_min_age_hours": 72,
                "cleanup_scope": [
                    "corp_identity_extracted_cache",
                    "office_template_import_package",
                ],
                "safety_note": SAFETY_NOTE,
            },
        }

    monkeypatch.setattr(
        disk_hygiene_service,
        "collect_backend_disk_hygiene_plan",
        fake_collect_backend_disk_hygiene_plan,
    )

    response = await client.get(
        "/admin/chat/api/panel/office-templates/disk-hygiene",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["policy"]["cleanup_scope"] == [
        "corp_identity_extracted_cache",
        "office_template_import_package",
    ]
    assert calls == [
        {
            "include_corp_identity_candidates": True,
            "include_office_import_candidates": True,
        }
    ]


@pytest.mark.asyncio
async def test_panel_office_disk_hygiene_manual_run_uses_explicit_cleanup(
    client,
    auth_headers,
    monkeypatch,
):
    calls: list[dict[str, object]] = []

    async def fake_run_backend_disk_hygiene(*args: object, **kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        return {
            "generated_at": "2026-04-21T00:00:00+00:00",
            "candidates": [],
            "totals": {"count": 0, "bytes_used": 0, "bytes_used_mb": 0.0, "by_kind": {}},
            "policy": {
                "corp_identity_cache_min_age_hours": 24,
                "office_import_stale_min_age_hours": 72,
                "cleanup_scope": [
                    "corp_identity_extracted_cache",
                    "office_template_import_package",
                ],
                "safety_note": SAFETY_NOTE,
            },
            "dry_run": False,
            "deleted": [{"kind": "office_template_import_package", "path": "/tmp/stale-package"}],
            "deleted_count": 1,
        }

    monkeypatch.setattr(
        disk_hygiene_service,
        "run_backend_disk_hygiene",
        fake_run_backend_disk_hygiene,
    )

    response = await client.post(
        "/admin/chat/api/panel/office-templates/disk-hygiene/run",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["deleted_count"] == 1
    assert calls == [
        {
            "dry_run": False,
            "include_corp_identity_candidates": True,
            "include_office_import_candidates": True,
        }
    ]
