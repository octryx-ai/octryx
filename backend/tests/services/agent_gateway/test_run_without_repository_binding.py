"""A run started without a repository is not refused at the device's repository check."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.agent_gateway.repository_root import run_repository_refusal
from app.services.knowledge.sources.sync.git_hosts import RepositoryLocation


@pytest.mark.asyncio
async def test_a_run_without_a_repository_accepts_the_folders_repository():
    location = RepositoryLocation(hostname="scm.example.test", path="scm/shop/demo-shop", host=None)
    assert await run_repository_refusal(None, SimpleNamespace(repository=None), location) is None
    assert await run_repository_refusal(None, SimpleNamespace(repository=""), location) is None
