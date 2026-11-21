from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.models import EngineeringKnowledgePack, EngineeringKnowledgePackVersion
from app.services.engineering_knowledge import archive_store
from app.services.engineering_knowledge.evidence_ledger import build_evidence_ledger
from app.services.engineering_knowledge.source_ingestion import ingest_engineering_knowledge_source


class FakeBody:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


class FakeS3Client:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kwargs):
        assert kwargs["Bucket"] == "engineering-archive-bucket"
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, **kwargs):
        assert kwargs["Bucket"] == "engineering-archive-bucket"
        return {"Body": FakeBody(self.objects[kwargs["Key"]])}

    def head_object(self, **kwargs):
        assert kwargs["Bucket"] == "engineering-archive-bucket"
        if kwargs["Key"] not in self.objects:
            raise KeyError(kwargs["Key"])
        return {}


def test_engineering_archive_store_round_trips_s3(monkeypatch):
    client = FakeS3Client()
    monkeypatch.setattr(archive_store.artifact_store.settings, "artifact_store_backend", "s3")
    monkeypatch.setattr(archive_store.artifact_store.settings, "artifact_store_bucket", "engineering-archive-bucket")
    monkeypatch.setattr(archive_store.artifact_store.settings, "artifact_store_prefix", "octryx")
    monkeypatch.setattr(archive_store.artifact_store, "_build_s3_client", lambda: client)

    archive_store.write_engineering_archive_text("engineering-knowledge/test/v1/source.txt", "hello")

    assert "octryx/engineering-knowledge/test/v1/source.txt" in client.objects
    assert archive_store.engineering_archive_exists("engineering-knowledge/test/v1/source.txt") is True
    assert archive_store.read_engineering_archive_text("engineering-knowledge/test/v1/source.txt") == "hello"


@pytest.mark.asyncio
async def test_source_ingestion_reads_parsed_archive_from_s3(db, tmp_path: Path, monkeypatch):
    client = FakeS3Client()
    monkeypatch.setattr(archive_store.artifact_store.settings, "artifact_store_backend", "s3")
    monkeypatch.setattr(archive_store.artifact_store.settings, "artifact_store_bucket", "engineering-archive-bucket")
    monkeypatch.setattr(archive_store.artifact_store.settings, "artifact_store_prefix", "octryx")
    monkeypatch.setattr(archive_store.artifact_store, "_build_s3_client", lambda: client)

    pack = EngineeringKnowledgePack(
        id=str(uuid.uuid4()),
        key="java-s3-pack",
        name="Java S3 Pack",
        stack_key="java",
        lifecycle_status="active",
        is_active=True,
    )
    version = EngineeringKnowledgePackVersion(
        id=str(uuid.uuid4()),
        pack_id=pack.id,
        version=1,
        status="draft",
        source_versions={"java": "21"},
        target_versions={"java": "25"},
        quality_status="pending",
    )
    db.add_all([pack, version])
    await db.flush()

    source_file = tmp_path / "oracle-java-25-migration.txt"
    source_file.write_text(
        "Java 25 migration guide. Use this source when migrating Java 21 code to Java 25.",
        encoding="utf-8",
    )
    source = await ingest_engineering_knowledge_source(
        db,
        pack_version=version,
        pack_slug=pack.key,
        source_spec={
            "source_key": "oracle-java-25-migration",
            "title": "Oracle Java 25 Migration Guide",
            "source_uri": str(source_file),
            "source_type": "migration_guide",
            "trust_tier": "official",
            "version_label": "25",
            "metadata": {
                "original_source_uri": "https://docs.oracle.com/en/java/javase/25/migrate/preparing-migration.html",
                "target_version": "25",
            },
        },
        archive_base_path=tmp_path,
        allowed_roots=[tmp_path],
    )

    assert source.raw_archive_path
    assert source.parsed_archive_path
    assert source.evidence_archive_path
    assert all(key.startswith("octryx/engineering-knowledge/java-s3-pack/v1/") for key in client.objects)

    facts = build_evidence_ledger(
        sources=[source],
        archive_base_path=tmp_path,
        stack_key="java",
        target_versions={"java": "25"},
    )
    assert facts
    assert facts[0]["source_key"] == "oracle-java-25-migration"
