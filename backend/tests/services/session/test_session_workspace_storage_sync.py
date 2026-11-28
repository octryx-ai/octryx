"""Session workspace storage config and sync: metadata round-trips, the DB config wins over env, full syncs mirror files by policy, a stopped session writes its manifest and an empty workspace is restored."""

import uuid

import pytest

from app.models import Session
from app.services.session import workspace_storage
from app.services.session.stop import finalize_user_stopped_session
from app.services.session.workspace import ensure_session_workspace_root
from app.services.session.workspace_storage import (
    SESSION_WORKSPACE_STORAGE_METADATA_KEY,
    SessionWorkspaceStorageConfig,
    get_session_workspace_storage_metadata,
    get_workspace_manifest,
    put_workspace_storage_object,
    resolve_session_workspace_storage_config,
    set_session_workspace_storage_metadata,
    workspace_current_object_key,
)
from app.services.session.workspace_sync import sync_workspace_full
from app.services.system_config import set_system_config_value
from app.services.system_config.constants import (
    AGENT_SESSION_WORKSPACE_STORAGE_BACKEND_KEY,
    AGENT_SESSION_WORKSPACE_STORAGE_BUCKET_KEY,
    AGENT_SESSION_WORKSPACE_STORAGE_PREFIX_KEY,
    AGENT_SESSION_WORKSPACE_SYNC_EXCLUDED_DIRS_KEY,
    AGENT_SESSION_WORKSPACE_SYNC_EXCLUDED_GLOBS_KEY,
    AGENT_SESSION_WORKSPACE_SYNC_MAX_FILE_COUNT_KEY,
    AGENT_SESSION_WORKSPACE_SYNC_MAX_FILE_SIZE_BYTES_KEY,
)


def test_session_workspace_storage_metadata_round_trips():
    session = Session(id=str(uuid.uuid4()), user_id="user-1", metadata_={})
    config = SessionWorkspaceStorageConfig(backend="s3", bucket="workspace-bucket", prefix="octryx/dev")

    set_session_workspace_storage_metadata(session, config)

    assert get_session_workspace_storage_metadata(session) == {
        "backend": "s3",
        "bucket": "workspace-bucket",
        "prefix": "octryx/dev",
        "object_scope": "sessions",
    }
    assert session.metadata_[SESSION_WORKSPACE_STORAGE_METADATA_KEY]["backend"] == "s3"


@pytest.mark.asyncio
async def test_resolve_session_workspace_storage_config_defaults_to_disabled(monkeypatch):
    async def fake_get_system_config_value(_db, _key):
        return None

    monkeypatch.setattr(workspace_storage, "get_system_config_value", fake_get_system_config_value)
    monkeypatch.delenv(workspace_storage.SESSION_WORKSPACE_STORAGE_BACKEND_ENV, raising=False)
    monkeypatch.delenv(workspace_storage.SESSION_WORKSPACE_STORAGE_BUCKET_ENV, raising=False)
    monkeypatch.delenv(workspace_storage.SESSION_WORKSPACE_STORAGE_PREFIX_ENV, raising=False)

    config = await resolve_session_workspace_storage_config(object())

    assert config == SessionWorkspaceStorageConfig()
    assert config.enabled is False


@pytest.mark.asyncio
async def test_resolve_session_workspace_storage_config_uses_db_before_env(monkeypatch):
    values = {
        workspace_storage.AGENT_SESSION_WORKSPACE_STORAGE_BACKEND_KEY: "s3",
        workspace_storage.AGENT_SESSION_WORKSPACE_STORAGE_BUCKET_KEY: "db-bucket",
        workspace_storage.AGENT_SESSION_WORKSPACE_STORAGE_PREFIX_KEY: "db-prefix",
    }

    async def fake_get_system_config_value(_db, key):
        return values.get(key)

    monkeypatch.setattr(workspace_storage, "get_system_config_value", fake_get_system_config_value)
    monkeypatch.setenv(workspace_storage.SESSION_WORKSPACE_STORAGE_BACKEND_ENV, "filesystem")
    monkeypatch.setenv(workspace_storage.SESSION_WORKSPACE_STORAGE_BUCKET_ENV, "env-bucket")
    monkeypatch.setenv(workspace_storage.SESSION_WORKSPACE_STORAGE_PREFIX_ENV, "env-prefix")

    config = await resolve_session_workspace_storage_config(object())

    assert config == SessionWorkspaceStorageConfig(backend="s3", bucket="db-bucket", prefix="db-prefix")


@pytest.mark.asyncio
async def test_sync_workspace_full_mirrors_files_and_writes_manifest(db, tmp_path):
    workspace_root = tmp_path / "workspace"
    storage_root = tmp_path / "objects"
    (workspace_root / "src").mkdir(parents=True)
    (workspace_root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (workspace_root / ".git").mkdir()
    (workspace_root / ".git" / "config").write_text("[core]\n", encoding="utf-8")

    session = Session(id="full-sync-session-1", user_id="user-1", metadata_={})
    db.add(session)
    await db.flush()

    async def fake_resolve_config(_db):
        return SessionWorkspaceStorageConfig(backend="filesystem", bucket=str(storage_root), prefix="octryx/full")

    result = await sync_workspace_full(
        db=db,
        session_id=session.id,
        workspace_root=workspace_root,
        reason="test_backfill",
        resolve_config_func=fake_resolve_config,
    )

    assert result["status"] == "synced"
    assert result["file_count"] == 1
    assert (
        storage_root / "octryx" / "full" / "sessions" / session.id / "workspace" / "current" / "src" / "app.py"
    ).read_text(encoding="utf-8") == "print('ok')\n"
    assert not (storage_root / "octryx" / "full" / "sessions" / session.id / "workspace" / "current" / ".git").exists()

    manifest = get_workspace_manifest(
        SessionWorkspaceStorageConfig(backend="filesystem", bucket=str(storage_root), prefix="octryx/full"),
        session_id=session.id,
    )
    assert manifest["reason"] == "test_backfill"
    assert manifest["file_count"] == 1
    assert manifest["files"] == [
        {
            "path": "src/app.py",
            "size_bytes": 12,
            "object_key": f"octryx/full/sessions/{session.id}/workspace/current/src/app.py",
        }
    ]
    assert session.metadata_["workspace_storage"]["backend"] == "filesystem"


@pytest.mark.asyncio
async def test_sync_workspace_full_respects_configured_policy(db, tmp_path):
    workspace_root = tmp_path / "workspace"
    storage_root = tmp_path / "objects"
    (workspace_root / "src").mkdir(parents=True)
    (workspace_root / "tmp").mkdir()
    (workspace_root / "src" / "keep.txt").write_text("keep\n", encoding="utf-8")
    (workspace_root / "src" / "skip.log").write_text("skip\n", encoding="utf-8")
    (workspace_root / "src" / "large.txt").write_text("large\n", encoding="utf-8")
    (workspace_root / "tmp" / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_SYNC_EXCLUDED_DIRS_KEY, value="tmp")
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_SYNC_EXCLUDED_GLOBS_KEY, value="*.log")
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_SYNC_MAX_FILE_SIZE_BYTES_KEY, value="5")
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_SYNC_MAX_FILE_COUNT_KEY, value="10")

    session = Session(id="policy-sync-session-1", user_id="user-1", metadata_={})
    db.add(session)
    await db.flush()

    async def fake_resolve_config(_db):
        return SessionWorkspaceStorageConfig(backend="filesystem", bucket=str(storage_root), prefix="octryx/policy")

    result = await sync_workspace_full(
        db=db,
        session_id=session.id,
        workspace_root=workspace_root,
        reason="policy_test",
        resolve_config_func=fake_resolve_config,
    )

    manifest = get_workspace_manifest(
        SessionWorkspaceStorageConfig(backend="filesystem", bucket=str(storage_root), prefix="octryx/policy"),
        session_id=session.id,
    )
    assert result["status"] == "synced"
    assert [item["path"] for item in manifest["files"]] == ["src/keep.txt"]
    assert (
        storage_root / "octryx" / "policy" / "sessions" / session.id / "workspace" / "current" / "src" / "keep.txt"
    ).exists()
    assert not (
        storage_root / "octryx" / "policy" / "sessions" / session.id / "workspace" / "current" / "src" / "skip.log"
    ).exists()


@pytest.mark.asyncio
async def test_finalize_user_stopped_session_writes_workspace_manifest(db, tmp_path):
    workspace_root = tmp_path / "workspace"
    storage_root = tmp_path / "objects"
    workspace_root.mkdir()
    (workspace_root / "notes.txt").write_text("stopped\n", encoding="utf-8")
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_BACKEND_KEY, value="filesystem")
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_BUCKET_KEY, value=str(storage_root))
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_PREFIX_KEY, value="octryx/stop")

    session = Session(
        id="stop-sync-session-1",
        user_id="user-1",
        status="running",
        metadata_={"workspace_root": str(workspace_root)},
    )
    db.add(session)
    await db.flush()

    await finalize_user_stopped_session(db, session=session)

    manifest = get_workspace_manifest(
        SessionWorkspaceStorageConfig(backend="filesystem", bucket=str(storage_root), prefix="octryx/stop"),
        session_id=session.id,
    )
    assert manifest["reason"] == "user_stopped"
    assert manifest["files"][0]["path"] == "notes.txt"
    assert (
        storage_root / "octryx" / "stop" / "sessions" / session.id / "workspace" / "current" / "notes.txt"
    ).read_text(encoding="utf-8") == "stopped\n"


@pytest.mark.asyncio
async def test_ensure_session_workspace_root_restores_empty_workspace_from_storage(db, tmp_path):
    workspace_root = tmp_path / "workspace"
    storage_root = tmp_path / "objects"
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_BACKEND_KEY, value="filesystem")
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_BUCKET_KEY, value=str(storage_root))
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_PREFIX_KEY, value="octryx/restore")
    config = SessionWorkspaceStorageConfig(backend="filesystem", bucket=str(storage_root), prefix="octryx/restore")
    put_workspace_storage_object(
        config,
        object_key=workspace_current_object_key(config, session_id="restore-session-1", relative_path="src/app.py"),
        payload=b"print('restored')\n",
    )

    session = Session(
        id="restore-session-1",
        user_id="user-1",
        metadata_={"workspace_root": str(workspace_root)},
    )
    db.add(session)
    await db.flush()

    restored_root = await ensure_session_workspace_root(db, session)

    assert restored_root == workspace_root.resolve()
    assert (workspace_root / "src" / "app.py").read_text(encoding="utf-8") == "print('restored')\n"
    assert session.metadata_["workspace_storage"]["backend"] == "filesystem"


@pytest.mark.asyncio
async def test_ensure_session_workspace_root_does_not_overwrite_non_empty_workspace(db, tmp_path):
    workspace_root = tmp_path / "workspace"
    storage_root = tmp_path / "objects"
    workspace_root.mkdir()
    (workspace_root / "local.txt").write_text("local\n", encoding="utf-8")
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_BACKEND_KEY, value="filesystem")
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_BUCKET_KEY, value=str(storage_root))
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_PREFIX_KEY, value="octryx/restore")
    config = SessionWorkspaceStorageConfig(backend="filesystem", bucket=str(storage_root), prefix="octryx/restore")
    put_workspace_storage_object(
        config,
        object_key=workspace_current_object_key(config, session_id="dirty-restore-session-1", relative_path="remote.txt"),
        payload=b"remote\n",
    )

    session = Session(
        id="dirty-restore-session-1",
        user_id="user-1",
        metadata_={"workspace_root": str(workspace_root)},
    )
    db.add(session)
    await db.flush()

    await ensure_session_workspace_root(db, session)

    assert (workspace_root / "local.txt").read_text(encoding="utf-8") == "local\n"
    assert not (workspace_root / "remote.txt").exists()
