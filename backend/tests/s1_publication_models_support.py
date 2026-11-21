"""Shared Alembic-built database fixtures and intent and receipt row builders for the S1 publication model tests."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.models import (
    DocumentationAudienceReceipt,
    DocumentationWriteIntent,
    Project,
    User,
    WorkflowRun,
    WorkflowRunDecision,
)
from app.models.runtime.documentation_publication import intent_marker
from tests.alembic_model_parity_support import DIALECTS, ScratchDatabase, migrated_database, scratch_database

INTENTS = DocumentationWriteIntent.__table__


RECEIPTS = DocumentationAudienceReceipt.__table__


NOW = dt.datetime(2026, 10, 13, 12, 0, 0)


HASH = "sha256:" + "a" * 64


@pytest.fixture(scope="module", params=DIALECTS)
def migrated_template(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[ScratchDatabase]:
    with migrated_database(request.param, tmp_path_factory.mktemp("s1-publication")) as database:
        yield database


@pytest.fixture
def database(migrated_template: ScratchDatabase, tmp_path: Path) -> Iterator[ScratchDatabase]:
    with scratch_database(migrated_template.dialect, tmp_path, template=migrated_template) as copy:
        yield copy


def _seed(connection: Connection) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:12]
    with OrmSession(bind=connection) as orm:
        requester = User(username=f"req-{suffix}", email=f"req-{suffix}@example.invalid", password_hash="x")
        audience = User(username=f"aud-{suffix}", email=f"aud-{suffix}@example.invalid", password_hash="x")
        orm.add_all([requester, audience])
        orm.flush()
        project = Project(name=f"s1-{suffix}")
        orm.add(project)
        orm.flush()
        runs = [
            WorkflowRun(workflow_kind="phased", workflow_key="b", requested_by=requester.id, project_id=project.id)
            for _ in range(2)
        ]
        orm.add_all(runs)
        orm.flush()
        decision = WorkflowRunDecision(run_id=runs[0].id, kind="confirmation", subject="publication",
                                       action="confirmed", payload_hash=HASH, decided_by=requester.id)
        orm.add(decision)
        orm.flush()
        ids = {"requester": requester.id, "audience": audience.id, "project": project.id, "run": runs[0].id,
               "other_run": runs[1].id, "decision": decision.id}
        orm.commit()
    return ids


def _intent(ids: dict[str, str], **overrides: Any) -> dict[str, Any]:
    operation_id = overrides.pop("operation_id", uuid.uuid4().hex)
    run_id = overrides.pop("run_id", ids["run"])
    row = {
        "id": str(uuid.uuid4()), "operation_id": operation_id, "marker": intent_marker(run_id, operation_id),
        "run_id": run_id, "slot": "feature_documentation", "node_id": "confirm_publication",
        "reserved_pass_key": "pass-1", "connection_id": "conn-1", "instance": "https://example.invalid/wiki",
        "space_id": "1001", "parent_id": "100001", "title": "Feature docs", "operation": "create",
        "expected_version": 1, "state": "reserved", "created_at": NOW, "updated_at": NOW,
    }
    row.update(overrides)
    return row


def _insert(database: ScratchDatabase, table, row: dict[str, Any]) -> None:
    database.run(lambda connection: connection.execute(table.insert().values(**row)))


def _refused(database: ScratchDatabase, table, row: dict[str, Any]) -> None:
    with pytest.raises(IntegrityError):
        _insert(database, table, row)


def _update(database: ScratchDatabase, table, where, values: dict[str, Any]) -> int:
    return database.run(lambda connection: connection.execute(update(table).where(*where).values(**values)).rowcount)
