from pathlib import Path

import pytest
from sqlalchemy import select

import app.services.artifact_store.service as artifact_store_module
from app.models import Message, Project, Session, ToolArtifact, ToolCall, User
from app.services.artifact_store import (
    delete_tool_artifacts_for_sessions,
    delete_tool_artifacts_for_tool_call_ids,
    persist_tool_artifact_payload,
    read_tool_artifact_payload,
    should_externalize_payload,
)
from app.services.tool_artifact import load_tool_artifact_payload


@pytest.mark.asyncio
async def test_persisted_tool_artifact_can_be_loaded_and_cleaned(db, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(artifact_store_module, "artifact_store_root", lambda: tmp_path)

    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(id="session-1", user_id=user.id, project_id=project.id, agent_type="diagnosis")
    db.add(session)
    db.add(
        Message(
            id="message-1",
            session_id=session.id,
            role="assistant",
            content="artifact source",
        )
    )
    await db.flush()

    payload = {"items": [{"name": "item-1", "value": "x" * 20}], "status": "ok"}
    metadata = await persist_tool_artifact_payload(
        db,
        artifact_id="artifact-1",
        session_id="session-1",
        message_id="message-1",
        tool_name="search_confluence",
        payload=payload,
        preview={"compact_result": {"status": "ok"}},
    )
    db.add(
        ToolCall(
            id="artifact-1",
            session_id="session-1",
            message_id="message-1",
            tool_name="search_confluence",
            parameters={},
            result={
                "_artifact_storage": "external_json_gzip",
                "artifact_id": "artifact-1",
                "payload_size_bytes": metadata["payload_size_bytes"],
                "content_sha256": metadata["content_sha256"],
                "preview": {"compact_result": {"status": "ok"}},
            },
            status="success",
        )
    )
    await db.commit()

    row = (await db.execute(select(ToolArtifact).where(ToolArtifact.id == "artifact-1"))).scalar_one()
    loaded = read_tool_artifact_payload(row)
    assert loaded == payload

    excerpt = await load_tool_artifact_payload(
        db,
        session_id="session-1",
        artifact_id="artifact-1",
        detail_level="excerpt",
        max_items=1,
    )
    assert excerpt["artifact_id"] == "artifact-1"
    assert excerpt["tool_name"] == "search_confluence"
    assert excerpt["result"]["items"][0]["name"] == "item-1"
    tool_call = (await db.execute(select(ToolCall).where(ToolCall.id == "artifact-1"))).scalar_one()
    assert tool_call.result["_artifact_storage"] == "external_json_gzip"
    assert "items" not in tool_call.result

    deleted = await delete_tool_artifacts_for_sessions(db, ["session-1"])
    await db.commit()
    assert deleted == 1
    assert not (tmp_path / Path(row.relative_path)).exists()


def test_should_externalize_payload_for_large_result():
    assert should_externalize_payload({"text": "x" * 20_000}) is True
    assert should_externalize_payload({"text": "small"}) is False


@pytest.mark.asyncio
async def test_persisted_tool_artifact_supports_s3_backend(db, monkeypatch):
    stored: dict[str, bytes] = {}

    class FakeBody:
        def __init__(self, payload: bytes):
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

    class FakeS3Client:
        def put_object(self, **kwargs):
            assert kwargs["Bucket"] == "artifact-bucket"
            assert kwargs["ContentType"] == "application/gzip"
            stored[kwargs["Key"]] = kwargs["Body"]

        def get_object(self, **kwargs):
            assert kwargs["Bucket"] == "artifact-bucket"
            return {"Body": FakeBody(stored[kwargs["Key"]])}

        def delete_object(self, **kwargs):
            assert kwargs["Bucket"] == "artifact-bucket"
            stored.pop(kwargs["Key"], None)

    monkeypatch.setattr(artifact_store_module.settings, "artifact_store_backend", "s3")
    monkeypatch.setattr(artifact_store_module.settings, "artifact_store_bucket", "artifact-bucket")
    monkeypatch.setattr(artifact_store_module.settings, "artifact_store_prefix", "octryx")
    monkeypatch.setattr(artifact_store_module, "_build_s3_client", lambda: FakeS3Client())

    payload = {"items": [{"name": "item-1"}], "status": "ok"}
    metadata = await persist_tool_artifact_payload(
        db,
        artifact_id="artifact-s3",
        session_id="session-s3",
        message_id="message-s3",
        tool_name="search_confluence",
        payload=payload,
        preview={"compact_result": {"status": "ok"}},
    )
    await db.commit()

    row = (await db.execute(select(ToolArtifact).where(ToolArtifact.id == "artifact-s3"))).scalar_one()
    loaded = read_tool_artifact_payload(row)
    assert loaded == payload
    assert metadata["storage_backend"] == "s3_json_gzip"
    assert row.relative_path.startswith("octryx/tool-artifacts/session-s3/")

    deleted = await delete_tool_artifacts_for_tool_call_ids(db, ["artifact-s3"])
    await db.commit()
    assert deleted == 1
    assert stored == {}


@pytest.mark.asyncio
async def test_persisted_tool_artifact_supports_gcs_backend(db, monkeypatch):
    stored: dict[str, bytes] = {}

    class FakeBlob:
        def __init__(self, key: str):
            self.key = key

        def upload_from_string(self, payload: bytes, content_type: str):
            assert content_type == "application/gzip"
            stored[self.key] = payload

        def download_as_bytes(self) -> bytes:
            return stored[self.key]

        def delete(self) -> None:
            stored.pop(self.key, None)

    class FakeBucket:
        def blob(self, key: str) -> FakeBlob:
            return FakeBlob(key)

    class FakeGcsClient:
        def bucket(self, bucket_name: str) -> FakeBucket:
            assert bucket_name == "artifact-bucket"
            return FakeBucket()

    monkeypatch.setattr(artifact_store_module.settings, "artifact_store_backend", "gcs")
    monkeypatch.setattr(artifact_store_module.settings, "artifact_store_bucket", "artifact-bucket")
    monkeypatch.setattr(artifact_store_module.settings, "artifact_store_prefix", "octryx-gcs")
    monkeypatch.setattr(artifact_store_module, "_build_gcs_client", lambda: FakeGcsClient())

    payload = {"items": [{"name": "item-2"}], "status": "ok"}
    metadata = await persist_tool_artifact_payload(
        db,
        artifact_id="artifact-gcs",
        session_id="session-gcs",
        message_id="message-gcs",
        tool_name="search_confluence",
        payload=payload,
        preview={"compact_result": {"status": "ok"}},
    )
    await db.commit()

    row = (await db.execute(select(ToolArtifact).where(ToolArtifact.id == "artifact-gcs"))).scalar_one()
    loaded = read_tool_artifact_payload(row)
    assert loaded == payload
    assert metadata["storage_backend"] == "gcs_json_gzip"
    assert row.relative_path.startswith("octryx-gcs/tool-artifacts/session-gcs/")

    deleted = await delete_tool_artifacts_for_tool_call_ids(db, ["artifact-gcs"])
    await db.commit()
    assert deleted == 1
    assert stored == {}
