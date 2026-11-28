"""Shared helpers for the test_knowledge_evidence_ledger_* modules."""

from __future__ import annotations

from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from tests.knowledge_evidence_seed_support import fetch_user, seed_member

FIRST = b"The Zurich datacenter hosts the primary cluster.\n\nFailover runs from Geneva.\n"


SECOND = b"The Zurich datacenter hosts the primary cluster.\n\nFailover now runs from Bern.\n"


async def _authorized(db, workspace_id: str):
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    user = await fetch_user(db, user_id)
    return await authorize_workspace(db, current_user=user, workspace_id=workspace_id, require_author=True)


async def _ingest(db, runtime, authorized, payload: bytes, *, source_key: str = "runbook", title: str = "Runbook"):
    return await ingest_text_source(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key=source_key,
        display_title=title,
        declared_media_type="text/plain; charset=utf-8",
        data=payload,
        created_by=authorized.project_id,
    )
