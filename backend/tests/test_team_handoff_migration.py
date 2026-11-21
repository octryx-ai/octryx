"""Alembic owns handoff persistence; database constraints reject unbound or duplicate owners."""
from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Project, User, WorkflowHandoff, WorkflowRun
from tests.alembic_model_parity_support import DIALECTS, migrated_database, scratch_database


@pytest.fixture(scope="module", params=DIALECTS)
def template(request, tmp_path_factory):
    with migrated_database(request.param, tmp_path_factory.mktemp("team-handoff-schema")) as database:
        yield database


@pytest.fixture
def database(template, tmp_path):
    with scratch_database(template.dialect, tmp_path, template=template) as database:
        yield database


def seed(connection):
    owner, workspace, parent, child = [str(uuid.uuid4()) for _ in range(4)]
    connection.execute(User.__table__.insert().values(
        id=owner, username=owner, email=f"{owner}@example.invalid", password_hash="fixture"))
    connection.execute(Project.__table__.insert().values(id=workspace, name=workspace))
    connection.execute(WorkflowRun.__table__.insert(), [
        {"id": run, "project_id": workspace, "requested_by": owner,
         "workflow_kind": "phased", "workflow_key": "handoff-fixture"} for run in (parent, child)])
    now = dt.datetime(2026, 10, 14, 1)
    offer = {"id": str(uuid.uuid4()), "parent_run_id": parent, "parent_node_id": "child", "parent_entry": 1,
             "parent_state_version": 1, "parent_version_id": "pinned", "child_descriptor": {},
             "workspace_id": workspace, "requested_by": owner, "target_kind": "person", "target_key": owner,
             "contract": {}, "envelopes": {}, "acceptance": "Inspect the exact approved artefact",
             "payload_hash": "sha256:" + "a" * 64, "issued_at": now, "expires_at": now + dt.timedelta(minutes=5)}
    return offer, child


@pytest.mark.parametrize("cause", ["accepted_without_receiver", "child_without_session", "duplicate_child"])
def test_database_refuses_unbound_or_duplicate_receiver(database, cause):
    offer, child = database.run(seed)
    if cause == "accepted_without_receiver":
        offer.update(state="accepted", owner_epoch=1)
    elif cause == "child_without_session":
        offer.update(child_run_id=child)
    else:
        # A valid existing Session is required before testing the unique child binding.
        from app.models import Session
        sid = str(uuid.uuid4())
        database.run(lambda c: c.execute(Session.__table__.insert().values(
            id=sid, user_id=offer["requested_by"], project_id=offer["workspace_id"])))
        offer.update(child_run_id=child, receiver_session_id=sid)
        database.run(lambda c: c.execute(WorkflowHandoff.__table__.insert().values(**offer)))
        offer = {**offer, "id": str(uuid.uuid4()), "parent_entry": 2}
    with pytest.raises(IntegrityError):
        database.run(lambda c: c.execute(WorkflowHandoff.__table__.insert().values(**offer)))
