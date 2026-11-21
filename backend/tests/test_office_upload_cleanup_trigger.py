from __future__ import annotations

import pytest

from app.services import disk_hygiene as disk_hygiene_service
from app.services.office import storage as office_storage


@pytest.mark.asyncio
async def test_office_upload_triggers_office_only_disk_hygiene(client, auth_headers, monkeypatch):
    cleanup_calls: list[dict[str, object]] = []

    async def fake_persist_uploaded_office_template(**_: object) -> dict[str, object]:
        return {
            "key": "deck",
            "name": "Deck",
            "doc_type": "pptx",
            "path": "/tmp/deck-ai.potx",
            "description": "AI-ready template",
            "is_default": False,
        }

    async def fake_run_backend_disk_hygiene(*args: object, **kwargs: object) -> dict[str, object]:
        cleanup_calls.append(dict(kwargs))
        return {"deleted_count": 0}

    monkeypatch.setattr(
        office_storage,
        "persist_uploaded_office_template",
        fake_persist_uploaded_office_template,
    )
    monkeypatch.setattr(
        disk_hygiene_service,
        "run_backend_disk_hygiene",
        fake_run_backend_disk_hygiene,
    )

    response = await client.post(
        "/admin/chat/api/panel/office-templates/upload",
        headers=auth_headers,
        files={
            "file": (
                "deck.potx",
                b"template-bytes",
                "application/vnd.openxmlformats-officedocument.presentationml.template",
            )
        },
    )

    assert response.status_code == 200
    assert cleanup_calls == [
        {
            "dry_run": False,
            "include_corp_identity_candidates": False,
            "include_office_import_candidates": True,
        }
    ]


@pytest.mark.asyncio
async def test_office_upload_cleanup_oserror_does_not_fail_upload(client, auth_headers, monkeypatch):
    async def fake_persist_uploaded_office_template(**_: object) -> dict[str, object]:
        return {
            "key": "deck",
            "name": "Deck",
            "doc_type": "pptx",
            "path": "/tmp/deck-ai.potx",
            "description": "AI-ready template",
            "is_default": False,
        }

    async def fake_run_backend_disk_hygiene(*args: object, **kwargs: object) -> dict[str, object]:
        raise OSError("cleanup unavailable")

    monkeypatch.setattr(
        office_storage,
        "persist_uploaded_office_template",
        fake_persist_uploaded_office_template,
    )
    monkeypatch.setattr(
        disk_hygiene_service,
        "run_backend_disk_hygiene",
        fake_run_backend_disk_hygiene,
    )

    response = await client.post(
        "/admin/chat/api/panel/office-templates/upload",
        headers=auth_headers,
        files={
            "file": (
                "deck.potx",
                b"template-bytes",
                "application/vnd.openxmlformats-officedocument.presentationml.template",
            )
        },
    )

    assert response.status_code == 200
