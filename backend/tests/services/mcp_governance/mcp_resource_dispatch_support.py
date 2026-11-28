"""Shared helpers for the test_mcp_resource_dispatch_* modules."""

from __future__ import annotations

from tests.support.mcp_resource_client_support import RecordingMcpResourceManager, install_mcp_manager
from tests.support.mcp_resource_support import (
    DOC_URI,
    PROMPT,
    SERVER,
    create_mcp_workspace,
    enable_binding,
    mirror_catalog,
    prompt_binding,
    resource_binding,
)


def _get(prompt_name: str = PROMPT) -> dict:
    return {"server_name": SERVER, "prompt_name": prompt_name, "arguments": {"topic": "react"}}


async def _enabled_resource_workspace(db, monkeypatch, *, risk: str = "read", scopes: list[str] | None = None):
    workspace = await create_mcp_workspace(db)
    manager = install_mcp_manager(monkeypatch, RecordingMcpResourceManager())
    await mirror_catalog(db, workspace, resources=[DOC_URI], prompts=[PROMPT])
    await enable_binding(db, await resource_binding(db, workspace, DOC_URI), risk=risk, scopes=scopes)
    await enable_binding(db, await prompt_binding(db, workspace, PROMPT), risk=risk, scopes=scopes)
    return workspace, manager
