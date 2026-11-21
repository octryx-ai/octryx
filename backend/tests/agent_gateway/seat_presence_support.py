"""Shared helpers for the test_seat_presence_* modules."""

# ruff: noqa: F811  (the shared ``anthropic`` fixture is imported, then requested by name)
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text

from app.models import OAuthGrant, Project
from app.services.agent_gateway.contract import GATEWAY_AUDIENCE, SCOPE_MODEL_INVOKE
from app.services.auth import create_access_token
from app.services.oauth_provider import mint_access_token
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace

REGISTER = "/api/v1/agent-gateway/sessions/register"


PRESENCE = "/api/v1/agent-gateway/presence"


POLICY = "/api/v1/agent-gateway/client-policy"


FINALIZE = "/api/v1/agent-gateway/sessions/finalize"


SEAT = "/api/v1/model-gateway/anthropic/seat/v1/messages"


SUBSCRIPTION = "sk-ant-oat01-" + "s" * 60  # the user's own subscription token: never stored anywhere


SEAT_POLICY = {"seat_mode": "allowed"}


async def _workspace(db, *, classification: str | None = "internal", policy: dict | None = None) -> str:
    workspace_id = await seed_workspace(db)
    project = await db.get(Project, workspace_id)
    config: dict[str, Any] = {}
    if classification:
        config["data_policy"] = {"classification": classification}
    if policy is not None:
        config["agent_gateway_policy"] = policy
    project.config = config
    await db.commit()
    return workspace_id


async def _gateway_headers(db, user_id: str, workspace_id: str, session_key: str | None = None) -> dict[str, str]:
    grant = OAuthGrant(id=str(uuid.uuid4()), user_id=user_id, client_id="octryx-claude-test", scopes=[SCOPE_MODEL_INVOKE])
    db.add(grant)
    await db.commit()
    token, _ = mint_access_token(user_id=user_id, client_id=grant.client_id, grant_id=grant.id,
                                 scopes=[SCOPE_MODEL_INVOKE], resource=GATEWAY_AUDIENCE)
    return {"authorization": f"Bearer {token}", "x-octryx-workspace": workspace_id,
            "x-octryx-session": session_key or str(uuid.uuid4())}


async def _register(client, headers: dict[str, str], profile: str = "seat"):
    return await client.post(REGISTER, json={"profile": profile, "branch": "feature/brd-6", "client": "octryx-claude",
                                             "client_version": "0.2.0"}, headers=headers)


def _seat_headers(gateway: dict[str, str], credential: str, **extra: str) -> dict[str, str]:
    return {
        "authorization": f"Bearer {SUBSCRIPTION}",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "oauth-2025-04-20",
        "accept": "application/json",
        "user-agent": "claude-cli/2.1.282",
        "x-app": "cli",
        "x-claude-code-session-id": "c0ffee00-1111-2222-3333-444455556666",
        "x-stainless-os": "MacOS",
        "x-api-key": "should-never-travel",
        "cookie": "octryx_session=browser-cookie",
        "x-octryx-session": gateway["x-octryx-session"],
        "x-octryx-workspace": gateway["x-octryx-workspace"],
        "x-octryx-seat-credential": credential,
        **extra,
    }


def _body(model: str = "claude-sonnet-5", text: str = "Fix the test.") -> dict[str, Any]:
    return {"model": model, "max_tokens": 64, "stream": True, "messages": [{"role": "user", "content": text}]}


async def _seat_session(client, db, *, classification="internal", policy=None, role="member"):
    workspace_id = await _workspace(db, classification=classification, policy=SEAT_POLICY if policy is None else policy)
    user_id = await seed_member(db, workspace_id=workspace_id, role=role)
    await db.commit()
    gateway = await _gateway_headers(db, user_id, workspace_id)
    registered = await _register(client, gateway)
    assert registered.status_code == 200, registered.text
    return workspace_id, user_id, gateway, registered.json()["seat_credential"]


# --- presence read model -------------------------------------------------------------------------------


async def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def _found_anywhere(db, needle: str) -> list[str]:
    """Every table/column whose text contains ``needle`` (the whole test database is searched)."""
    found = []
    tables = (await db.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))).scalars().all()
    for table in tables:
        columns = [row[1] for row in (await db.execute(text(f'PRAGMA table_info("{table}")'))).all()]
        for column in columns:
            hit = (await db.execute(text(f'SELECT 1 FROM "{table}" WHERE CAST("{column}" AS TEXT) LIKE :needle LIMIT 1'),
                                    {"needle": f"%{needle}%"})).first()
            if hit:
                found.append(f"{table}.{column}")
    return found
