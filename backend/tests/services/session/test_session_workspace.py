import uuid
from pathlib import Path

import pytest

from app.models import Session
from app.services.session.workspace import (
    SESSION_WORKSPACE_METADATA_KEY,
    ensure_session_workspace_root,
    ensure_workspace_path,
    search_session_workspace_entries,
    serialize_session_workspace_children,
)


def test_ensure_workspace_path_rejects_paths_outside_root(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()

    with pytest.raises(ValueError, match="inside the session workspace"):
        ensure_workspace_path(root, "../escape.txt")


def test_workspace_serializers_keep_directory_first_ordering(tmp_path):
    root = tmp_path / "workspace"
    nested = root / "docs"
    nested.mkdir(parents=True)
    (root / "b.txt").write_text("b", encoding="utf-8")
    (root / "a.txt").write_text("a", encoding="utf-8")

    entries = serialize_session_workspace_children(root)

    assert [entry["name"] for entry in entries] == ["docs", "a.txt", "b.txt"]
    assert [entry["kind"] for entry in entries] == ["directory", "file", "file"]


def test_search_session_workspace_entries_includes_parent_directories(tmp_path):
    root = tmp_path / "workspace"
    target_dir = root / "docs" / "guides"
    target_dir.mkdir(parents=True)
    (target_dir / "alpha.txt").write_text("alpha", encoding="utf-8")

    entries = search_session_workspace_entries(root, query="alpha")
    relative_paths = [entry["relativePath"] for entry in entries]

    assert relative_paths == ["docs", "docs/guides", "docs/guides/alpha.txt"]


@pytest.mark.asyncio
async def test_ensure_session_workspace_root_uses_metadata_root_without_overwriting(db, tmp_path):
    session = Session(id=str(uuid.uuid4()), user_id="user-1", metadata_={})
    db.add(session)
    await db.flush()

    configured_root = (tmp_path / "configured-root").resolve()
    session.metadata_ = {SESSION_WORKSPACE_METADATA_KEY: str(configured_root)}

    ensured = await ensure_session_workspace_root(db, session)

    assert ensured == configured_root
    assert Path(session.metadata_[SESSION_WORKSPACE_METADATA_KEY]) == configured_root
