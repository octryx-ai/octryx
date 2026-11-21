from __future__ import annotations

from pathlib import Path

import pytest

from app.services.office import storage as office_storage


def _chunk_reader(payload: bytes):
    cursor = 0

    async def read_chunk(size: int) -> bytes:
        nonlocal cursor
        if cursor >= len(payload):
            return b""
        chunk = payload[cursor : cursor + size]
        cursor += len(chunk)
        return chunk

    return read_chunk


async def _close_file() -> None:
    return None


def _pptx_entry_for(source_template: str | Path, import_root: str | Path) -> dict[str, object]:
    source_path = Path(source_template).resolve()
    package_root = Path(import_root).resolve() / f"pkg-{source_path.stem}"
    ai_root = package_root / "ai-template"
    ai_root.mkdir(parents=True, exist_ok=True)
    ai_template_path = ai_root / "deck-ai.potx"
    ai_template_path.write_text("stub", encoding="utf-8")
    manifest_path = package_root / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    return {
        "key": "deck",
        "name": "Deck Ai Template",
        "doc_type": "pptx",
        "path": str(ai_template_path),
        "description": "AI-ready PPTX template generated from uploaded source.",
        "is_default": False,
        "source_path": str(source_path),
        "ai_template_path": str(ai_template_path),
        "package_manifest_path": str(manifest_path),
        "storage_contract": {
            "doc_type": "pptx",
            "storage_kind": "uploaded_source_with_generated_ai_template",
            "source_path": str(source_path),
            "active_template_path": str(ai_template_path),
            "package_root": str(package_root),
            "generated_artifact_root": str(ai_root),
            "package_manifest_path": str(manifest_path),
            "ai_template_path": str(ai_template_path),
            "has_import_package": True,
            "has_generated_ai_artifact": True,
        },
    }


def _docx_entry_for(source_template: str | Path) -> dict[str, object]:
    source_path = Path(source_template).resolve()
    return {
        "key": "doc-template",
        "name": "Doc Template",
        "doc_type": "docx",
        "path": str(source_path),
        "description": "",
        "is_default": False,
        "source_path": str(source_path),
        "storage_contract": {
            "doc_type": "docx",
            "storage_kind": "uploaded_source_only",
            "source_path": str(source_path),
            "active_template_path": str(source_path),
            "has_import_package": False,
            "has_generated_ai_artifact": False,
        },
    }


@pytest.mark.asyncio
async def test_duplicate_pptx_upload_reuses_existing_storage_contract(monkeypatch, tmp_path: Path) -> None:
    upload_root = tmp_path / "office-uploads"
    import_root = tmp_path / "office-imports"
    payload = b"same-pptx-template"
    build_calls = 0

    def fake_build_uploaded_office_template_entry(
        *,
        source_template: str | Path,
        import_root: str | Path,
    ) -> dict[str, object]:
        nonlocal build_calls
        build_calls += 1
        return _pptx_entry_for(source_template, import_root)

    monkeypatch.setattr(
        office_storage,
        "build_uploaded_office_template_entry",
        fake_build_uploaded_office_template_entry,
    )

    first = await office_storage.persist_uploaded_office_template(
        file_name="brand-template.potx",
        read_chunk=_chunk_reader(payload),
        close_file=_close_file,
        upload_root=upload_root,
        import_root=import_root,
    )
    second = await office_storage.persist_uploaded_office_template(
        file_name="duplicate-brand-template.potx",
        read_chunk=_chunk_reader(payload),
        close_file=_close_file,
        upload_root=upload_root,
        import_root=import_root,
    )

    stored_sources = [
        path
        for path in upload_root.iterdir()
        if path.is_file() and not path.name.endswith(office_storage.OFFICE_TEMPLATE_UPLOAD_METADATA_SUFFIX)
    ]

    assert build_calls == 1
    assert second == first
    assert len(stored_sources) == 1
    assert len(list(upload_root.glob(f"*{office_storage.OFFICE_TEMPLATE_UPLOAD_METADATA_SUFFIX}"))) == 1


@pytest.mark.asyncio
async def test_duplicate_docx_upload_reuses_existing_source_only_contract(monkeypatch, tmp_path: Path) -> None:
    upload_root = tmp_path / "office-uploads"
    import_root = tmp_path / "office-imports"
    payload = b"same-docx-template"
    build_calls = 0

    def fake_build_uploaded_office_template_entry(
        *,
        source_template: str | Path,
        import_root: str | Path,
    ) -> dict[str, object]:
        nonlocal build_calls
        build_calls += 1
        return _docx_entry_for(source_template)

    monkeypatch.setattr(
        office_storage,
        "build_uploaded_office_template_entry",
        fake_build_uploaded_office_template_entry,
    )

    first = await office_storage.persist_uploaded_office_template(
        file_name="corp-template.dotx",
        read_chunk=_chunk_reader(payload),
        close_file=_close_file,
        upload_root=upload_root,
        import_root=import_root,
    )
    second = await office_storage.persist_uploaded_office_template(
        file_name="copy-corp-template.dotx",
        read_chunk=_chunk_reader(payload),
        close_file=_close_file,
        upload_root=upload_root,
        import_root=import_root,
    )

    assert build_calls == 1
    assert second == first


@pytest.mark.asyncio
async def test_duplicate_upload_rebuilds_when_existing_artifacts_are_missing(monkeypatch, tmp_path: Path) -> None:
    upload_root = tmp_path / "office-uploads"
    import_root = tmp_path / "office-imports"
    payload = b"same-pptx-template"
    build_calls = 0

    def fake_build_uploaded_office_template_entry(
        *,
        source_template: str | Path,
        import_root: str | Path,
    ) -> dict[str, object]:
        nonlocal build_calls
        build_calls += 1
        return _pptx_entry_for(source_template, import_root)

    monkeypatch.setattr(
        office_storage,
        "build_uploaded_office_template_entry",
        fake_build_uploaded_office_template_entry,
    )

    first = await office_storage.persist_uploaded_office_template(
        file_name="brand-template.potx",
        read_chunk=_chunk_reader(payload),
        close_file=_close_file,
        upload_root=upload_root,
        import_root=import_root,
    )
    Path(str(first["path"])).unlink()

    second = await office_storage.persist_uploaded_office_template(
        file_name="brand-template-again.potx",
        read_chunk=_chunk_reader(payload),
        close_file=_close_file,
        upload_root=upload_root,
        import_root=import_root,
    )

    assert build_calls == 2
    assert second["source_path"] != first["source_path"]
