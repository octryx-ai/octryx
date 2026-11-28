"""Shared helpers for the test_confluence_cloud_freshness_corrections_* modules."""

from __future__ import annotations

import httpx
from sqlalchemy import select

from app.models.project.knowledge_source_sync import KnowledgeSourceConnector, KnowledgeSourceSyncItem
from app.services.knowledge.sources.sync.service_run import run_connector

HIDDEN = "557058:hidden"


def _transport(stub, *, rewrite=None, failing: set[str] = frozenset(), seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request.url)
        if request.url.path.rsplit("/", 1)[-1] in failing:
            return httpx.Response(500, json={"message": "boom"})
        status, payload, headers = stub.handle(
            request.method, request.url.raw_path.decode(), request.headers.get("Authorization")
        )
        if rewrite is not None and status == 200:
            rewrite(request.url.path, payload)
        return httpx.Response(status, json=payload, headers=headers)

    return httpx.MockTransport(handler)


async def _run(db, setup, stub, *, trigger="manual", **transport):
    authorized, user_id, runtime, row = setup
    return await run_connector(
        db, runtime=runtime, authorized=authorized, row=await db.get(KnowledgeSourceConnector, row.id),
        actor_id=user_id, transport=_transport(stub, **transport), trigger=trigger,
    )


async def _item(db, setup, external_id: str) -> KnowledgeSourceSyncItem:
    statement = select(KnowledgeSourceSyncItem).where(
        KnowledgeSourceSyncItem.connector_id == setup[3].id, KnowledgeSourceSyncItem.external_id == external_id
    )
    item = (await db.execute(statement)).scalar_one()
    await db.refresh(item)
    return item


def _on_listing(change):
    def rewrite(path: str, payload: dict) -> None:
        if path.endswith(("/rest/api/content", "/rest/api/content/search")):
            change(payload)

    return rewrite
