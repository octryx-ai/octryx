"""``GET /api/v1/agent-gateway/workspaces``: the launcher's login lists the Workspaces it may use (--workspace NAME)."""

from __future__ import annotations

import uuid

import pytest

from app.models import OAuthGrant
from app.models.security.user import UserProject
from app.services.agent_gateway.contract import GATEWAY_AUDIENCE, SCOPE_MODEL_INVOKE
from app.services.oauth_provider import mint_access_token
from tests.agent_gateway.seat_presence_support import _workspace
from tests.knowledge_evidence_seed_support import seed_member

PATH = "/api/v1/agent-gateway/workspaces"


async def _token(db, user_id: str, *, bound: list[str] | None = None, scopes=(SCOPE_MODEL_INVOKE,)) -> dict[str, str]:
    grant = OAuthGrant(id=str(uuid.uuid4()), user_id=user_id, client_id="octryx-claude-test", scopes=list(scopes),
                       project_ids=bound)
    db.add(grant)
    await db.commit()
    token, _ = mint_access_token(user_id=user_id, client_id=grant.client_id, grant_id=grant.id, scopes=list(scopes),
                                 resource=GATEWAY_AUDIENCE)
    return {"authorization": f"Bearer {token}"}  # no session and no Workspace header


@pytest.mark.asyncio
async def test_the_launcher_login_lists_its_workspaces_without_a_session(client, db):
    from app.models import Project

    first, second, foreign = await _workspace(db), await _workspace(db), await _workspace(db)
    (await db.get(Project, first)).name = "Acme Orders"
    (await db.get(Project, second)).name = "alpha"
    user = await seed_member(db, workspace_id=first, role="member")
    db.add(UserProject(user_id=user, project_id=second, role="owner"))
    await db.commit()

    listed = await client.get(PATH, headers=await _token(db, user))
    bound = await client.get(PATH, headers=await _token(db, user, bound=[first]))
    missing = await client.get(PATH)
    wrong_scope = await client.get(PATH, headers=await _token(db, user, scopes=("knowledge:read",)))

    assert listed.status_code == 200
    assert listed.json() == {"items": [{"id": first, "name": "Acme Orders"}, {"id": second, "name": "alpha"}]}
    assert foreign not in listed.text
    assert bound.json() == {"items": [{"id": first, "name": "Acme Orders"}]}
    assert missing.status_code == 401 and wrong_scope.status_code == 403
