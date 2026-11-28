"""Shared helpers for the test_mcp_knowledge_* modules."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.project.knowledge_evidence import KnowledgeEvidenceSpan, KnowledgeProjectionOutboxEntry
from app.services import mcp_knowledge_protocol


async def _call_native_mcp_tool(token: str, tool_name: str, arguments: dict):
    protocol_app = mcp_knowledge_protocol.create_knowledge_mcp_protocol_app()
    async with _native_mcp_lifespan(protocol_app):
        async with _NativeMcpTestClient(
            transport=ASGITransport(app=protocol_app),
            base_url="http://localhost:8000",
            token=token,
        ) as protocol_client:
            await _initialize_native_mcp(protocol_client)
            response = await _mcp_json_rpc(
                protocol_client,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                },
            )
            result = response["result"]
            return SimpleNamespace(
                isError=bool(result.get("isError", False)),
                structuredContent=result.get("structuredContent"),
                content=result.get("content"),
            )


async def _initialize_native_mcp(protocol_client: AsyncClient) -> None:
    await _mcp_json_rpc(
        protocol_client,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "octryx-test", "version": "1"},
            },
        },
    )
    initialized = await protocol_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=_native_mcp_headers(protocol_client),
    )
    assert initialized.status_code in {200, 202}, initialized.text


async def _mcp_json_rpc(protocol_client: AsyncClient, payload: dict) -> dict:
    response = await protocol_client.post("/mcp", json=payload, headers=_native_mcp_headers(protocol_client))
    assert response.status_code == 200, response.text
    return response.json()


def _native_mcp_headers(protocol_client: AsyncClient) -> dict[str, str]:
    token = getattr(protocol_client, "_token")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }


@asynccontextmanager
async def _native_mcp_lifespan(protocol_app) -> AsyncIterator[None]:
    async with protocol_app.router.lifespan_context(protocol_app):
        yield


class _NativeMcpTestClient(AsyncClient):
    def __init__(self, *args, token: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._token = token

    def stream(self, method: str, url, **kwargs):
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Authorization"] = f"Bearer {self._token}"
        return super().stream(method, url, headers=headers, **kwargs)


def _native_mcp_session_factory(db: AsyncSession):
    return async_sessionmaker(bind=db.bind, class_=AsyncSession, expire_on_commit=False)


async def _outbox_states_for_revision(db: AsyncSession, revision_id: str) -> list[str]:
    return (
        (
            await db.execute(
                select(KnowledgeProjectionOutboxEntry.state).where(
                    KnowledgeProjectionOutboxEntry.revision_id == revision_id
                )
            )
        )
        .scalars()
        .all()
    )


async def _span_texts_for_revision(db: AsyncSession, revision_id: str) -> list[str]:
    return (
        (
            await db.execute(
                select(KnowledgeEvidenceSpan.text).where(KnowledgeEvidenceSpan.revision_id == revision_id)
            )
        )
        .scalars()
        .all()
    )
