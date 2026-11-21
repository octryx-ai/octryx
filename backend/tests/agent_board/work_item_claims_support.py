"""Shared helpers for the test_work_item_claims_* modules."""

from __future__ import annotations

import uuid

import pytest

from app.models import User
from app.services.agent_board.claims import claim_work_item
from app.services.agent_board.fencing import fenced_handlers
from tests.agent_gateway.seat_presence_support import _workspace
from tests.knowledge_evidence_seed_support import seed_member


async def _claim(db, identity, item, *, paths=None, lease=900):
    return await claim_work_item(db, item=item, kind=identity.kind, ref_hash=identity.ref_hash,
                                 user_id=identity.user_id, paths=paths, lease_seconds=lease)


async def _two_members(db):
    workspace_id = await _workspace(db)
    anna = await seed_member(db, workspace_id=workspace_id, role="member", username=f"anna{uuid.uuid4().hex[:6]}")
    ben = await seed_member(db, workspace_id=workspace_id, role="member", username=f"ben{uuid.uuid4().hex[:6]}")
    await db.commit()
    return workspace_id, anna, ben


def _code(exc: pytest.ExceptionInfo) -> tuple[int, object]:
    detail = exc.value.detail
    return exc.value.status_code, detail.get("code") if isinstance(detail, dict) else detail


# --- fencing ----------------------------------------------------------------------------------------------


async def _fenced(db, user_id, scope, tool, arguments, *, session_key=None):
    calls = []

    async def write(session, *, user, scope, arguments):
        calls.append(arguments)
        return {"ok": True}

    headers = {"x-octryx-session": session_key} if session_key else {}
    handlers = fenced_handlers({tool: write, "work_item_find": write}, headers=headers)
    user = await db.get(User, user_id)
    return await handlers[tool](db, user=user, scope=scope, arguments=arguments), calls
