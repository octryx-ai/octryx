import uuid

import pytest

from app.models import Session
from app.services.session.run_state import (
    RUN_STATUS_COMPLETED,
    get_session_run_completion_reason,
    get_session_run_status,
    set_session_run_state,
)
from app.services.session.shared import get_session_metadata, get_session_metadata_text
from app.services.session.workspace import SESSION_WORKSPACE_METADATA_KEY, ensure_session_workspace_root


def test_session_shared_metadata_helpers_copy_and_normalize():
    session = Session(id=str(uuid.uuid4()), user_id="user-1", metadata_={"workspace_root": " /tmp/example "})

    metadata = get_session_metadata(session)
    metadata["workspace_root"] = "/tmp/changed"

    assert session.metadata_["workspace_root"] == " /tmp/example "
    assert get_session_metadata_text(session, "workspace_root") == "/tmp/example"


def test_set_session_run_state_uses_shared_metadata_helpers():
    session = Session(id=str(uuid.uuid4()), user_id="user-1", metadata_={"workspace_root": "/tmp/workspace"})

    set_session_run_state(session, RUN_STATUS_COMPLETED, "no_changes_needed")

    assert get_session_run_status(session) == RUN_STATUS_COMPLETED
    assert get_session_run_completion_reason(session) == "no_changes_needed"
    assert session.metadata_["workspace_root"] == "/tmp/workspace"


@pytest.mark.asyncio
async def test_ensure_session_workspace_root_sets_metadata_once(db, tmp_path):
    session = Session(id=str(uuid.uuid4()), user_id="user-1", metadata_={})
    db.add(session)
    await db.flush()

    root = tmp_path / "session-workspaces" / session.id
    session.metadata_ = {SESSION_WORKSPACE_METADATA_KEY: str(root)}

    ensured = await ensure_session_workspace_root(db, session)

    assert ensured == root.resolve()
    assert get_session_metadata_text(session, SESSION_WORKSPACE_METADATA_KEY) == str(root.resolve())
