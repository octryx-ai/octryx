from pathlib import Path

import pytest

from app.services.document_ingestion import archive_store, ingest_document_source


class FakeBody:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


class FakeS3Client:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kwargs):
        assert kwargs["Bucket"] == "document-archive-bucket"
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, **kwargs):
        assert kwargs["Bucket"] == "document-archive-bucket"
        return {"Body": FakeBody(self.objects[kwargs["Key"]])}

    def head_object(self, **kwargs):
        assert kwargs["Bucket"] == "document-archive-bucket"
        if kwargs["Key"] not in self.objects:
            raise KeyError(kwargs["Key"])
        return {}


@pytest.mark.asyncio
async def test_ingest_document_source_archives_artifacts_to_s3(tmp_path: Path, monkeypatch):
    client = FakeS3Client()
    monkeypatch.setattr(archive_store.artifact_store.settings, "artifact_store_backend", "s3")
    monkeypatch.setattr(archive_store.artifact_store.settings, "artifact_store_bucket", "document-archive-bucket")
    monkeypatch.setattr(archive_store.artifact_store.settings, "artifact_store_prefix", "octryx")
    monkeypatch.setattr(archive_store.artifact_store, "_build_s3_client", lambda: client)

    source = tmp_path / "architecture.pdf"
    source.write_bytes(b"%PDF-1.4\nArchitecture handbook text\n%%EOF")

    result = await ingest_document_source(
        db=None,
        workspace_root=tmp_path,
        path=str(source),
        title_hint="Architecture Handbook",
        topic="Architecture",
        bundle_id="architecture-handbook",
    )

    archived = result["archive_artifacts"]
    assert archived
    assert {item["storage_backend"] for item in archived} == {"s3"}
    assert any(item["name"] == "architecture.pdf" for item in archived)
    assert all(item["object_key"].startswith("octryx/document-ingestion/architecture-handbook/") for item in archived)
    assert client.objects
    assert result["source"]["archive_storage_backend"] == "s3"
    assert result["source"]["archive_artifacts"] == archived
