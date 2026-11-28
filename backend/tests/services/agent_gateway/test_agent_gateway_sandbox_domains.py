"""The Workspace's sandbox network domains for governed Claude Code sessions."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import Project, User
from app.models.security.oauth_provider import OAuthGrant
from app.services.agent_gateway.contract import GATEWAY_AUDIENCE, SCOPE_MODEL_INVOKE
from app.services.agent_gateway.policy_keys import AgentGatewayPolicyError
from app.services.agent_gateway.policy_normalize import normalize_agent_gateway_policy
from app.services.oauth_provider import mint_access_token


async def _project(db) -> Project:
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    config = dict(project.config or {})
    config.pop("agent_gateway_policy", None)
    project.config = config
    await db.commit()
    return project


async def _gateway_headers(db, project: Project) -> dict[str, str]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    grant = OAuthGrant(user_id=admin.id, client_id=f"oec_sbx_{uuid.uuid4().hex[:6]}", scopes=[SCOPE_MODEL_INVOKE])
    db.add(grant)
    await db.commit()
    token, _ = mint_access_token(user_id=admin.id, client_id=grant.client_id, grant_id=grant.id,
                                 scopes=[SCOPE_MODEL_INVOKE], resource=GATEWAY_AUDIENCE)
    return {"Authorization": f"Bearer {token}", "X-Octryx-Session": str(uuid.uuid4()),
            "X-Octryx-Workspace": project.id}


@pytest.mark.asyncio
async def test_an_admin_sets_the_sandbox_domains_and_the_launcher_gets_them(client, db, auth_headers):
    project = await _project(db)
    url = f"/api/v1/workspaces/{project.id}/agent-gateway/sandbox"
    assert (await client.get(url, headers=auth_headers)).json()["allowed_domains"] == []

    put = await client.put(url, headers=auth_headers,
                           json={"allowed_domains": ["PyPI.org", "*.npmjs.org", "*.npmjs.org"]})
    assert put.status_code == 200 and put.json()["allowed_domains"] == ["pypi.org", "*.npmjs.org"]
    await db.refresh(project)
    stored = project.config["agent_gateway_policy"]
    # Starting from the baseline keeps its deny rules.
    assert any(rule["id"] == "no-force-push" for rule in stored["tool_rules"])

    policy = await client.get("/api/v1/agent-gateway/client-policy", headers=await _gateway_headers(db, project))
    assert policy.json()["sandbox"] == {"allowed_domains": ["pypi.org", "*.npmjs.org"],
                                        "unsandboxed_commands": [], "network": "open"}

    bad = await client.put(url, headers=auth_headers, json={"allowed_domains": ["https://evil.example/x"]})
    assert bad.status_code == 400


@pytest.mark.parametrize(
    "entry",
    ["https://packages.example.com", "packages.example.com/simple", "packages.example.com:443", "localhost", "*", "*.",
     "a..b", "", "user@packages.example.com"],
)
def test_invalid_sandbox_domains_are_refused(entry):
    with pytest.raises(AgentGatewayPolicyError):
        normalize_agent_gateway_policy({"sandbox": {"allowed_domains": [entry]}})


def test_the_platform_host_is_never_an_allowed_domain(monkeypatch):
    monkeypatch.setattr(get_settings(), "platform_public_origin", "https://octryx.example.test")
    with pytest.raises(AgentGatewayPolicyError) as refused:
        normalize_agent_gateway_policy({"sandbox": {"allowed_domains": ["*.octryx.example.test"]}})
    assert refused.value.reason == "platform_host_not_allowed"
    assert normalize_agent_gateway_policy({"sandbox": {"allowed_domains": ["packages.example.com"]}})["sandbox"] == {
        "allowed_domains": ["packages.example.com"]
    }
