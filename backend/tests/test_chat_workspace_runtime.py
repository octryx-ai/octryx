"""Tests for runtime settings, workspace API, task dependency, and entity versions."""

from datetime import timedelta

import pytest

from app.services.system_config import set_system_config_value
from app.services.system_config.constants import (
    AGENT_SESSION_WORKSPACE_STORAGE_BACKEND_KEY,
    AGENT_SESSION_WORKSPACE_STORAGE_BUCKET_KEY,
    AGENT_SESSION_WORKSPACE_STORAGE_PREFIX_KEY,
)
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_runtime_settings_include_session_workspace_config_and_cleanup_endpoint(
    client,
    auth_headers,
    tmp_path,
):
    workspace_base = tmp_path / "session-workspaces"
    update_resp = await client.put(
        "/admin/chat/api/panel/runtime-settings",
        headers=auth_headers,
        json={
            "session_workspace_base_dir": str(workspace_base),
            "session_workspace_max_age_hours": 1,
        },
    )
    assert update_resp.status_code == 200
    payload = update_resp.json()
    assert payload["session_workspace_base_dir"] == str(workspace_base.resolve())
    assert payload["session_workspace_max_age_hours"] == 1

    stale_dir = workspace_base / "stale-session"
    stale_dir.mkdir(parents=True, exist_ok=True)
    old_timestamp = (utc_now() - timedelta(hours=3)).timestamp()
    stale_dir.touch()
    import os

    os.utime(stale_dir, (old_timestamp, old_timestamp))

    cleanup_resp = await client.post(
        "/admin/chat/api/panel/runtime-workspace/cleanup",
        headers=auth_headers,
    )
    assert cleanup_resp.status_code == 200
    cleanup_payload = cleanup_resp.json()
    assert "stale-session" in cleanup_payload["deleted"]
    assert not stale_dir.exists()


async def _configure_workspace_storage(client, auth_headers, db, workspace_base, storage_root) -> None:
    settings_resp = await client.put(
        "/admin/chat/api/panel/runtime-settings",
        headers=auth_headers,
        json={
            "session_workspace_base_dir": str(workspace_base),
            "session_workspace_max_age_hours": 24,
        },
    )
    assert settings_resp.status_code == 200
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_BACKEND_KEY, value="filesystem")
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_BUCKET_KEY, value=str(storage_root))
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_PREFIX_KEY, value="octryx/api")
    await db.commit()


async def _assert_workspace_tree_and_search(client, auth_headers, session_id: str) -> None:
    """The root lists only top-level entries; deeper levels load per path; search returns the file and its parents."""
    tree_resp = await client.get(
        f"/admin/chat/api/sessions/{session_id}/workspace",
        headers=auth_headers,
    )
    assert tree_resp.status_code == 200
    tree_payload = tree_resp.json()
    relative_paths = {entry["relativePath"]: entry["kind"] for entry in tree_payload["files"]}
    assert relative_paths["repo"] == "directory"
    assert tree_payload["loadedDirectories"] == [""]

    repo_tree_resp = await client.get(
        f"/admin/chat/api/sessions/{session_id}/workspace/tree?path=repo",
        headers=auth_headers,
    )
    assert repo_tree_resp.status_code == 200
    repo_relative_paths = {entry["relativePath"]: entry["kind"] for entry in repo_tree_resp.json()["files"]}
    assert repo_relative_paths["repo/src"] == "directory"

    src_tree_resp = await client.get(
        f"/admin/chat/api/sessions/{session_id}/workspace/tree?path=repo/src",
        headers=auth_headers,
    )
    assert src_tree_resp.status_code == 200
    src_relative_paths = {entry["relativePath"]: entry["kind"] for entry in src_tree_resp.json()["files"]}
    assert src_relative_paths["repo/src/app.py"] == "file"

    search_resp = await client.get(
        f"/admin/chat/api/sessions/{session_id}/workspace/search?q=app.py",
        headers=auth_headers,
    )
    assert search_resp.status_code == 200
    search_relative_paths = {entry["relativePath"]: entry["kind"] for entry in search_resp.json()["files"]}
    assert search_relative_paths["repo"] == "directory"
    assert search_relative_paths["repo/src"] == "directory"
    assert search_relative_paths["repo/src/app.py"] == "file"


async def _rename_move_delete_and_clean(
    client, auth_headers, session_id: str, workspace_root, storage_root, source_file, source_object
) -> None:
    """Each action changes the local workspace and the mirrored storage object alike."""
    rename_resp = await client.post(
        f"/admin/chat/api/sessions/{session_id}/workspace/rename",
        headers=auth_headers,
        json={"path": "repo/src/app.py", "new_name": "main.py"},
    )
    assert rename_resp.status_code == 200
    assert not source_file.exists()
    assert (workspace_root / "repo" / "src" / "main.py").exists()
    renamed_object = (
        storage_root / "octryx" / "api" / "sessions" / session_id / "workspace" / "current" / "repo" / "src" / "main.py"
    )
    assert not source_object.exists()
    assert renamed_object.read_text(encoding="utf-8") == "print('workspace')\n"

    move_resp = await client.post(
        f"/admin/chat/api/sessions/{session_id}/workspace/move",
        headers=auth_headers,
        json={"paths": ["repo/src/main.py"], "target_directory": "archive"},
    )
    assert move_resp.status_code == 200
    moved_file = workspace_root / "archive" / "main.py"
    assert moved_file.exists()
    moved_object = storage_root / "octryx" / "api" / "sessions" / session_id / "workspace" / "current" / "archive" / "main.py"
    assert not renamed_object.exists()
    assert moved_object.read_text(encoding="utf-8") == "print('workspace')\n"

    delete_resp = await client.post(
        f"/admin/chat/api/sessions/{session_id}/workspace/delete",
        headers=auth_headers,
        json={"paths": ["archive/main.py"]},
    )
    assert delete_resp.status_code == 200
    assert not moved_file.exists()
    assert not moved_object.exists()

    clean_resp = await client.post(
        f"/admin/chat/api/sessions/{session_id}/workspace/clean",
        headers=auth_headers,
    )
    assert clean_resp.status_code == 200
    assert list(workspace_root.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_session_workspace_api_supports_tree_and_file_actions(client, auth_headers, db, tmp_path):
    workspace_base = tmp_path / "session-workspaces"
    storage_root = tmp_path / "session-workspace-objects"
    await _configure_workspace_storage(client, auth_headers, db, workspace_base, storage_root)

    session_resp = await client.post(
        "/api/v1/sessions",
        json={"agent_type": "diagnosis"},
        headers=auth_headers,
    )
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]
    workspace_root = workspace_base / session_id

    workspace_resp = await client.get(
        f"/admin/chat/api/sessions/{session_id}/workspace",
        headers=auth_headers,
    )
    assert workspace_resp.status_code == 200
    assert workspace_resp.json()["rootPath"] == str(workspace_root.resolve())

    create_folder_resp = await client.post(
        f"/admin/chat/api/sessions/{session_id}/workspace/folders",
        headers=auth_headers,
        json={"path": "repo/src"},
    )
    assert create_folder_resp.status_code == 200
    assert (workspace_root / "repo" / "src").is_dir()

    source_file = workspace_root / "repo" / "src" / "app.py"
    source_file.write_text("print('workspace')\n", encoding="utf-8")
    source_object = (
        storage_root / "octryx" / "api" / "sessions" / session_id / "workspace" / "current" / "repo" / "src" / "app.py"
    )
    source_object.parent.mkdir(parents=True, exist_ok=True)
    source_object.write_text("print('workspace')\n", encoding="utf-8")

    await _assert_workspace_tree_and_search(client, auth_headers, session_id)
    await _rename_move_delete_and_clean(
        client, auth_headers, session_id, workspace_root, storage_root, source_file, source_object
    )


@pytest.mark.asyncio
async def test_session_chat_upload_syncs_to_workspace_storage(client, auth_headers, db, tmp_path):
    workspace_base = tmp_path / "session-workspaces"
    storage_root = tmp_path / "session-workspace-objects"
    settings_resp = await client.put(
        "/admin/chat/api/panel/runtime-settings",
        headers=auth_headers,
        json={
            "session_workspace_base_dir": str(workspace_base),
            "session_workspace_max_age_hours": 24,
        },
    )
    assert settings_resp.status_code == 200
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_BACKEND_KEY, value="filesystem")
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_BUCKET_KEY, value=str(storage_root))
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_PREFIX_KEY, value="octryx/upload")
    await db.commit()

    session_resp = await client.post(
        "/api/v1/sessions",
        json={"agent_type": "diagnosis"},
        headers=auth_headers,
    )
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    upload_resp = await client.post(
        "/admin/chat/api/upload",
        headers=auth_headers,
        data={"session_id": session_id},
        files={"files": ("context.txt", b"uploaded\n", "text/plain")},
    )

    assert upload_resp.status_code == 200
    uploaded = upload_resp.json()["files"][0]
    assert uploaded["workspaceSync"]["status"] == "synced"
    assert uploaded["relativePath"].startswith("uploads/")
    assert (
        storage_root
        / "octryx"
        / "upload"
        / "sessions"
        / session_id
        / "workspace"
        / "current"
        / uploaded["relativePath"]
    ).read_text(encoding="utf-8") == "uploaded\n"
