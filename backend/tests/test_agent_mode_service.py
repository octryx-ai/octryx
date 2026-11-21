"""A4: run modes are code-defined labels; resolving one never reads or writes the database."""

from __future__ import annotations

import pytest

from app.agent.runtime_defaults import SYSTEM_AGENT_MODE_DEFINITIONS
from app.services.agent_mode import known_agent_mode_keys, list_agent_modes, resolve_agent_mode


@pytest.mark.asyncio
async def test_resolve_agent_mode_reads_the_shipped_definitions_only():
    assert (await resolve_agent_mode(None, None)).key == "diagnosis"
    assert (await resolve_agent_mode(None, "missing-mode")).key == "diagnosis"
    chat = await resolve_agent_mode(None, "Chat")
    assert (chat.key, chat.capability_type) == ("chat", "diagnosis")
    assert (await resolve_agent_mode(None, "coding")).capability_type == "change"


@pytest.mark.asyncio
async def test_the_mode_list_is_the_shipped_catalog():
    modes = list_agent_modes()
    assert [mode.key for mode in modes] == [definition.key for definition in SYSTEM_AGENT_MODE_DEFINITIONS]
    assert known_agent_mode_keys() == frozenset(mode.key for mode in modes)
    assert all(mode.is_system and mode.is_active for mode in modes)
