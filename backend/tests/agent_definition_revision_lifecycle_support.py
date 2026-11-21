"""Shared helpers for the test_agent_definition_revision_lifecycle_* modules."""

from __future__ import annotations

import pytest

import app.services.agent_definition_revisions as revisions_module


def _force_revision_number(monkeypatch: pytest.MonkeyPatch, number: int) -> None:
    """Make the next insert reuse *number*, as a concurrent request would."""

    async def _stale(*_args, **_kwargs) -> int:
        return number

    monkeypatch.setattr(revisions_module, "next_revision_number", _stale)
