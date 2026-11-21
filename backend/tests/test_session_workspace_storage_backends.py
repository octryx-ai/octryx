"""Session workspace storage keys and backends: prefixes and keys are scoped and reject escapes, and the filesystem and S3 backends round-trip objects and manifests."""

import pytest

from app.services.session.workspace_storage import (
    SessionWorkspaceStorageConfig,
    delete_workspace_storage_object,
    get_workspace_manifest,
    get_workspace_storage_object,
    list_workspace_storage_objects,
    normalize_workspace_object_relative_path,
    normalize_workspace_storage_backend,
    normalize_workspace_storage_object_key,
    normalize_workspace_storage_prefix,
    put_workspace_manifest,
    put_workspace_storage_object,
    workspace_current_object_key,
    workspace_event_object_key,
    workspace_manifest_object_key,
    workspace_snapshot_object_key,
)


def test_workspace_storage_backend_defaults_to_disabled_for_unknown_values():
    assert normalize_workspace_storage_backend(None) == "disabled"
    assert normalize_workspace_storage_backend("s3") == "s3"
    assert normalize_workspace_storage_backend("filesystem") == "filesystem"
    assert normalize_workspace_storage_backend("unexpected") == "disabled"


def test_workspace_storage_prefix_is_relative_and_normalized():
    assert normalize_workspace_storage_prefix("///") == ""
    assert normalize_workspace_storage_prefix("tenant-a/env/dev/") == "tenant-a/env/dev"
    assert normalize_workspace_storage_prefix(r"tenant-a\\dev") == "tenant-a/dev"

    with pytest.raises(ValueError, match="relative"):
        normalize_workspace_storage_prefix("/absolute")
    with pytest.raises(ValueError, match="parent"):
        normalize_workspace_storage_prefix("tenant/../other")


def test_workspace_object_relative_path_rejects_escape_segments():
    assert normalize_workspace_object_relative_path("src/app.py") == "src/app.py"
    assert normalize_workspace_object_relative_path(r"src\\app.py") == "src/app.py"

    for raw_path in ("", "/absolute.txt", "../escape.txt", "src/../../escape.txt"):
        with pytest.raises(ValueError):
            normalize_workspace_object_relative_path(raw_path)


def test_workspace_storage_object_key_rejects_escape_segments():
    assert normalize_workspace_storage_object_key("sessions/session-1/manifest.json") == "sessions/session-1/manifest.json"

    for object_key in ("/sessions/session-1/manifest.json", "sessions/../other/manifest.json"):
        with pytest.raises(ValueError):
            normalize_workspace_storage_object_key(object_key)


def test_workspace_object_keys_are_session_scoped_and_stable():
    config = SessionWorkspaceStorageConfig(backend="s3", bucket="workspace-bucket", prefix="octryx/dev")

    assert (
        workspace_current_object_key(config, session_id="session/one", relative_path="src/app.py")
        == "octryx/dev/sessions/session-one/workspace/current/src/app.py"
    )
    assert (
        workspace_snapshot_object_key(config, session_id="session/one", revision="rev/1", relative_path="src/app.py")
        == "octryx/dev/sessions/session-one/snapshots/rev-1/src/app.py"
    )
    assert (
        workspace_event_object_key(config, session_id="session/one", event_id="write file")
        == "octryx/dev/sessions/session-one/events/write-file.json"
    )
    assert workspace_manifest_object_key(config, session_id="session/one") == "octryx/dev/sessions/session-one/manifest.json"


def test_filesystem_workspace_storage_backend_round_trips_objects(tmp_path):
    config = SessionWorkspaceStorageConfig(backend="filesystem", bucket=str(tmp_path), prefix="octryx/dev")
    key = workspace_current_object_key(config, session_id="session-1", relative_path="src/app.py")

    written = put_workspace_storage_object(config, object_key=key, payload=b"print('ok')\n", content_type="text/x-python")

    assert written.key == "octryx/dev/sessions/session-1/workspace/current/src/app.py"
    assert written.size_bytes == 12
    assert get_workspace_storage_object(config, object_key=key) == b"print('ok')\n"
    assert [item.key for item in list_workspace_storage_objects(config, object_prefix="octryx/dev/sessions/session-1")] == [
        "octryx/dev/sessions/session-1/workspace/current/src/app.py"
    ]

    delete_workspace_storage_object(config, object_key=key)

    assert list_workspace_storage_objects(config, object_prefix="octryx/dev/sessions/session-1") == []


def test_workspace_storage_manifest_round_trips_on_filesystem(tmp_path):
    config = SessionWorkspaceStorageConfig(backend="filesystem", bucket=str(tmp_path), prefix="octryx/dev")
    manifest = {"session_id": "session-1", "files": [{"path": "src/app.py", "size": 12}]}

    written = put_workspace_manifest(config, session_id="session-1", manifest=manifest)

    assert written.key == "octryx/dev/sessions/session-1/manifest.json"
    assert get_workspace_manifest(config, session_id="session-1") == manifest


def test_s3_workspace_storage_backend_round_trips_objects():
    stored: dict[str, bytes] = {}

    class FakeBody:
        def __init__(self, payload: bytes):
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

    class FakeS3Client:
        def put_object(self, **kwargs):
            assert kwargs["Bucket"] == "workspace-bucket"
            assert kwargs["ContentType"] == "text/plain"
            stored[kwargs["Key"]] = kwargs["Body"]

        def get_object(self, **kwargs):
            assert kwargs["Bucket"] == "workspace-bucket"
            return {"Body": FakeBody(stored[kwargs["Key"]])}

        def list_objects_v2(self, **kwargs):
            assert kwargs["Bucket"] == "workspace-bucket"
            prefix = kwargs["Prefix"]
            return {
                "Contents": [
                    {"Key": key, "Size": len(payload), "ETag": '"etag-1"'}
                    for key, payload in sorted(stored.items())
                    if key.startswith(prefix)
                ]
            }

        def delete_object(self, **kwargs):
            assert kwargs["Bucket"] == "workspace-bucket"
            stored.pop(kwargs["Key"], None)

    client = FakeS3Client()
    config = SessionWorkspaceStorageConfig(backend="s3", bucket="workspace-bucket", prefix="octryx/dev")
    key = workspace_current_object_key(config, session_id="session-1", relative_path="notes.txt")

    written = put_workspace_storage_object(
        config,
        object_key=key,
        payload=b"hello",
        content_type="text/plain",
        s3_client_factory=lambda: client,
    )

    assert written.key == "octryx/dev/sessions/session-1/workspace/current/notes.txt"
    assert get_workspace_storage_object(config, object_key=key, s3_client_factory=lambda: client) == b"hello"
    listed = list_workspace_storage_objects(
        config,
        object_prefix="octryx/dev/sessions/session-1",
        s3_client_factory=lambda: client,
    )
    assert [(item.key, item.size_bytes, item.etag) for item in listed] == [
        ("octryx/dev/sessions/session-1/workspace/current/notes.txt", 5, "etag-1")
    ]

    delete_workspace_storage_object(config, object_key=key, s3_client_factory=lambda: client)

    assert stored == {}


def test_s3_workspace_storage_backend_requires_bucket():
    config = SessionWorkspaceStorageConfig(backend="s3")

    with pytest.raises(RuntimeError, match="bucket"):
        put_workspace_storage_object(config, object_key="sessions/session-1/manifest.json", payload=b"{}")


def test_workspace_storage_operations_reject_disabled_backend():
    config = SessionWorkspaceStorageConfig()

    with pytest.raises(RuntimeError, match="disabled"):
        get_workspace_storage_object(config, object_key="sessions/session-1/manifest.json")
