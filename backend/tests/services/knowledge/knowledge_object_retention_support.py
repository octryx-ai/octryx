"""Shared helpers for the test_knowledge_object_retention_* modules."""

from __future__ import annotations

from app.models.project.knowledge_object_retention import RETENTION_MODE_REPORT_ONLY
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.retention.policy import set_retention_policy
from app.services.knowledge.runtime import EvidenceRuntime
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member
from tests.services.knowledge.knowledge_retention_support import FakeMaintenanceClient, maintenance

ABANDONED = b"Bytes whose ledger transaction never committed.\n\nSecond paragraph.\n"


INGESTED = b"The Zurich datacenter hosts the primary cluster.\n\nFailover runs from Geneva.\n"


OPERATOR = "cli:acceptance"


def _wired():
    client = FakeMaintenanceClient()
    runtime, _, _ = build_runtime(s3=client.source)
    return runtime, maintenance(client), client


async def _authorized(db, workspace_id: str):
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    user = await fetch_user(db, user_id)
    return await authorize_workspace(db, current_user=user, workspace_id=workspace_id, require_author=True)


async def _abandon(runtime: EvidenceRuntime, client: FakeMaintenanceClient, authorized, *, age_hours: int) -> str:
    stored = await runtime.object_store.put_if_absent(authorized.workspace, ABANDONED)
    client.age(stored.ref.key, hours=age_hours)
    return stored.ref.key


async def _ingest(db, runtime, authorized, payload: bytes = INGESTED, *, source_key: str = "runbook"):
    return await ingest_text_source(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key=source_key,
        display_title="Runbook",
        declared_media_type="text/plain",
        data=payload,
        created_by=authorized.project_id,
    )


async def _set_policy(db, project_id: str, *, min_age_hours: int = 24, legal_hold: bool = False):
    return await set_retention_policy(
        db,
        project_id=project_id,
        mode=RETENTION_MODE_REPORT_ONLY,
        min_object_age_hours=min_age_hours,
        legal_hold=legal_hold,
        updated_by=None,
    )
