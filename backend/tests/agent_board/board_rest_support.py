"""Shared helpers for the test_board_rest_* modules."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import User
from app.services.mcp_agent_board_tools import board_tool_handlers
from tests.agent_board.support import scope_for, seed_presence
from tests.agent_gateway.seat_presence_support import _bearer, _workspace
from tests.knowledge_evidence_seed_support import seed_member, seed_outsider

BOARD = "/api/v1/agent-board"


class Team:
    """A Workspace with an owner, an admin, two members (Anna runs an agent), and an outsider."""

    async def build(self, db):
        self.ws = await _workspace(db)
        self.owner = await seed_member(db, workspace_id=self.ws, role="owner")
        self.admin = await seed_member(db, workspace_id=self.ws, role="admin")
        self.anna = await seed_member(db, workspace_id=self.ws, role="member")
        self.ben = await seed_member(db, workspace_id=self.ws, role="member")
        self.outsider = await seed_outsider(db)
        self.anna_key = await seed_presence(db, self.anna, self.ws)
        self.platform_admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one().id
        await db.commit()
        return self

    async def post(self, db, **arguments):
        user, scope = await scope_for(db, self.anna)
        handler = board_tool_handlers({"x-octryx-session": self.anna_key})["board_post"]
        result = await handler(db, user=user, scope=scope, arguments={"project_id": self.ws, **arguments})
        await db.commit()
        return result["message"]


@pytest.fixture
async def team(db):
    return await Team().build(db)


async def _get(client, path, user_id, **params):
    return await client.get(f"{BOARD}{path}", params=params, headers=await _bearer(user_id))


async def _post(client, path, user_id, body=None):
    return await client.post(f"{BOARD}{path}", json=body or {}, headers=await _bearer(user_id))


async def _decide(client, message_id, user_id, **body):
    return await _post(client, f"/messages/{message_id}/decision", user_id, body)
