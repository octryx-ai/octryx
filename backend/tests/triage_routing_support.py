"""Shared helpers for the test_triage_routing_* modules."""

from __future__ import annotations

import copy
import uuid

import pytest

from app.models.runtime.secure_work import WorkItem
from tests.phased_seed_definitions import seed_definitions


def _triage_seed() -> dict:
    return copy.deepcopy(next(seed for seed in seed_definitions() if seed["key"] == "jira-intake-triage")["definition"])


async def _item(db, *, project_id: str | None = None, source_type: str = "jira",
                issue_type: str | None = None) -> WorkItem:
    item = WorkItem(source_type=source_type, source_instance="test", source_key=f"PAY-{uuid.uuid4().hex[:5].upper()}",
                    source_project_key="PAY", title="Totals", project_id=project_id, issue_type=issue_type,
                    work_state="development")
    db.add(item)
    await db.flush()
    return item


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
