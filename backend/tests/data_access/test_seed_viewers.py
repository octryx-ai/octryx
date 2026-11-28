from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import app.db as app_db
from app.db import core as db_core
from app.models import AuditLog, Project, WorkflowRun
from app.services.data_access import reading_as
from app.services.data_access.viewer import AUDIT_ACTION
from app.services.knowledge import runtime as knowledge_runtime
from app.services.knowledge.ingestion import text_ingest
from tests.services.knowledge.test_demo_profile import _load
from tests.test_sample_runs import _bundle, _demo, _factory, run_bundle


@pytest.fixture
def maintenance_audit_in_test_session(db, monkeypatch):
    monkeypatch.setattr(db_core, "async_session_factory", _factory(db))
    monkeypatch.setattr(app_db, "async_session_factory", _factory(db))


async def _audited(db, reason: str) -> bool:
    return (await db.execute(select(AuditLog.id).where(AuditLog.action == AUDIT_ACTION,
                                                       AuditLog.resource_id == reason))).first() is not None


async def test_the_demo_sample_run_imports_with_no_viewer_set(db, auth_user, monkeypatch,
                                                              maintenance_audit_in_test_session):
    monkeypatch.setenv("OCTRYX_DEMO", "1")
    _source, bundle = await _bundle(db)
    await _demo(db, auth_user)
    with reading_as(None):
        new = await run_bundle.import_bundle(json.loads(run_bundle.dumps(bundle)), workspace="Demo Shop",
                                             github="http://127.0.0.1:8434", session_factory=_factory(db))
    assert new is not None and await db.get(WorkflowRun, new) is not None
    assert await _audited(db, "run bundle: import a sample run (demo seeding)")


async def test_the_demo_knowledge_step_runs_with_no_viewer_set(db, auth_user, monkeypatch,
                                                               maintenance_audit_in_test_session):
    seed = _load("seed_demo")
    project, _item = await _demo(db, auth_user)
    ingested: list[str] = []

    async def ingest(_db, **kwargs):
        ingested.append(kwargs["source_key"])
        return SimpleNamespace(created=True)

    monkeypatch.setattr(knowledge_runtime, "get_evidence_runtime", lambda: object())
    monkeypatch.setattr(text_ingest, "ingest_text_source", ingest)
    with reading_as(None):
        await seed._knowledge(project.id)
    assert sorted(ingested) == sorted(seed.source_key(name) for name in seed.knowledge_files())
    assert (await db.get(Project, project.id)).config["data_policy"]["classification"] == "internal"
    assert await _audited(db, "demo seed: the Demo Shop knowledge sources")
