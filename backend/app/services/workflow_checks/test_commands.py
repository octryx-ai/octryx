"""Which shell commands are test runs in a session's Workspace.

The Workspace's octryx-claude verification policy (``agent_gateway_policy.verification.test_command_prefixes``)
names its test commands; chat reads the same list, so ``pytest`` run through ``bash`` is a test run in chat as it
is at octryx-claude's Stop gate. A Workspace without its own list uses the default prefixes.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session
from .test_results import DEFAULT_TEST_PREFIXES


async def workspace_test_prefixes(db: AsyncSession | None, session_id: str | None) -> tuple[tuple[str, ...], ...]:
    session = await db.get(Session, session_id) if db is not None and session_id else None
    if session is None or not session.project_id:
        return DEFAULT_TEST_PREFIXES
    from ..agent_gateway.policy import load_workspace_policy

    loaded = await load_workspace_policy(db, session.project_id)
    verification = loaded.policy.verification if loaded.policy is not None else None
    return tuple(verification.test_command_prefixes) if verification is not None else DEFAULT_TEST_PREFIXES


__all__ = ["workspace_test_prefixes"]
