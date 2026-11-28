"""Shared helpers for the test_knowledge_evidence_isolation_* modules."""

from __future__ import annotations

from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from tests.knowledge_evidence_seed_support import fetch_user, seed_member

SHARED_BYTES = b"The Zurich datacenter hosts the primary cluster.\n\nFailover runs from Geneva.\n"


async def _authorized(db, workspace_id: str, *, role: str = "admin"):
    user_id = await seed_member(db, workspace_id=workspace_id, role=role)
    return await authorize_workspace(
        db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id
    )


async def _ingest(db, runtime, authorized, payload=SHARED_BYTES, *, source_key="runbook"):
    return await ingest_text_source(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key=source_key,
        display_title="Runbook",
        declared_media_type="text/plain",
        data=payload,
        created_by=None,
    )
