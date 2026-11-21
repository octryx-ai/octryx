"""Named AWS connections: several accounts per Workspace, each a role or a key pair.

- a call names its ``account_id`` (or its ``connection``): it runs with exactly that account's role or keys,
  never with the default's host profile (real chat tool, fake boto);
- the default serves its own ``aws_account_id``; another account and a call without one (several
  candidates) are refused, the latter listing the candidates;
- a named account whose keys or role are not available at call time is refused (no host default chain);
- ``allow_platform_credentials`` keeps its meaning per connection: over MCP a named connection with only the
  opt-in runs on the platform's credentials and is audited, one with a role is not;
- the admin API needs a key pair, a role or the opt-in; secrets stay write-only;
- the CLI paths (``_aws_env``) assume the configured role instead of passing the host's credentials.
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import AuditLog
from app.services.admin.project.named_connection_service import save_named
from app.services.admin.project.named_connection_view import list_named
from app.services.mcp_extra_tools import EXTRA_GOVERNED_MCP_TOOLS
from app.services.mcp_governed_knowledge import GOVERNED_MCP_TOOLS, McpCaller, run_governed_mcp_tool
from app.services.named_connections.routes_model import (
    NAMED_CONNECTIONS_KEY,
    NamedConnectionRoutes,
    ResolvedNamedConnection,
)
from app.services.named_connections.tool_routing import routed_execute
from app.services.tool_config import upsert_tool_config
from app.tools.connectors import aws_core
from app.tools.connectors.aws_compute import ListAwsEksClustersTool
from app.tools.context import ToolContext
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace

PROD, NON_PROD, OTHER = "222222222222", "111111111111", "333333333333"
DEFAULT = {"aws_region": "eu-central-1", "aws_profile": "platform", "aws_account_id": NON_PROD}
ROLE = "arn:aws:iam::222222222222:role/octryx-read"


def _prod(**config) -> ResolvedNamedConnection:
    return ResolvedNamedConnection("id-prod", "aws", "prod", "workspace", frozenset({PROD}),
                                   config or {"aws_region": "eu-west-1", "aws_role_arn": ROLE})


def _context(*named: ResolvedNamedConnection) -> ToolContext:
    config = {**DEFAULT, NAMED_CONNECTIONS_KEY: NamedConnectionRoutes(tuple(named))}
    return ToolContext(user_id="u", project_ids=["p"], roles=["admin"], session_id="s", project_config=config)


class FakeBoto:
    def __init__(self, seen: list[dict]):
        self.seen = seen

    def client(self, service: str):
        seen = self.seen

        class Client:
            def list_clusters(self, **kwargs):
                return {"clusters": ["demo-eks"]}

            def get_paginator(self, name):
                class Paginator:
                    def paginate(self, **kwargs):
                        return [{"clusters": ["demo-eks"]}]
                return Paginator()

        seen.append({"service": service})
        return Client()


@pytest.fixture
def boto(monkeypatch):
    seen: list[dict] = []

    def session(context):
        seen.append({key: context.project_config.get(key) for key in
                     ("aws_region", "aws_profile", "aws_role_arn", "aws_access_key_id")})
        return FakeBoto(seen)

    async def assume(context, current):
        if context.project_config.get("aws_role_arn"):
            seen.append({"assumed": context.project_config["aws_role_arn"]})
        return current

    monkeypatch.setattr(aws_core, "_get_boto_session", session)
    monkeypatch.setattr(aws_core, "_assume_role_if_needed", assume)
    return seen


async def test_an_account_runs_with_its_own_role_never_the_default_profile(boto) -> None:
    result = await routed_execute("list_aws_eks_clusters", {"account_id": PROD}, _context(_prod()),
                                  ListAwsEksClustersTool().execute)
    assert result["clusters"] == ["demo-eks"]
    assert boto[0] == {"aws_region": "eu-west-1", "aws_profile": None, "aws_role_arn": ROLE, "aws_access_key_id": None}
    assert {"assumed": ROLE} in boto


async def test_the_default_serves_its_account_and_everything_else_is_refused(boto) -> None:
    await routed_execute("list_aws_eks_clusters", {"account_id": NON_PROD}, _context(_prod()),
                         ListAwsEksClustersTool().execute)
    assert boto[0]["aws_profile"] == "platform"
    other = await routed_execute("list_aws_eks_clusters", {"account_id": OTHER}, _context(_prod()),
                                 ListAwsEksClustersTool().execute)
    assert other["code"] == "connection_not_configured_for_scope"
    ambiguous = await routed_execute("list_aws_eks_clusters", {}, _context(_prod()), ListAwsEksClustersTool().execute)
    assert ambiguous["code"] == "connection_ambiguous"
    assert [c["id"] for c in ambiguous["candidates"]] == ["id-prod", "default"] and "account" in ambiguous["error"]
    assert len([entry for entry in boto if "aws_profile" in entry]) == 1


@pytest.mark.parametrize("config", [
    {"aws_role_arn": ROLE},
    {"aws_region": "eu-west-1"},
    {"aws_region": "eu-west-1", "aws_access_key_id": "AKIAEXAMPLE"},
    {"aws_region": "eu-west-1", "aws_role_arn": " "},
])
async def test_without_its_keys_or_role_a_named_account_is_refused(boto, config) -> None:
    refused = await routed_execute("list_aws_eks_clusters", {"account_id": PROD}, _context(_prod(**config)),
                                   ListAwsEksClustersTool().execute)
    assert refused["code"] == "named_connection_credential_unavailable" and boto == []


async def test_the_admin_api_needs_keys_a_role_or_the_opt_in(db) -> None:
    workspace_id = await seed_workspace(db)
    await upsert_tool_config(db, tool_name="aws", project_id=workspace_id, config=dict(DEFAULT), is_active=True)
    body = {"name": "prod", "bound_scopes": [PROD], "aws_region": "eu-west-1"}
    no_region = {"name": "prod", "bound_scopes": [PROD], "aws_role_arn": ROLE}
    for refused_body in (body, {**body, "aws_access_key_id": "AKIAEXAMPLE"}, no_region):
        with pytest.raises(HTTPException) as refused:
            await save_named(db, connector="aws", project_id=workspace_id, payload=refused_body, actor_id=None)
        assert refused.value.status_code == 422
    with pytest.raises(HTTPException) as bad_account:
        await save_named(db, connector="aws", project_id=workspace_id, actor_id=None,
                         payload={**body, "bound_scopes": ["12345"], "aws_role_arn": ROLE})
    assert bad_account.value.detail["code"] == "named_connection_scopes_invalid"
    keys = await save_named(db, connector="aws", project_id=workspace_id, actor_id=None, payload={
        **body, "aws_access_key_id": "AKIAEXAMPLE", "aws_secret_access_key": "fake-secret-key-1"})
    assert keys["secret_status"] == {"aws_access_key_id": True, "aws_secret_access_key": True,
                                     "aws_session_token": False}
    opt_in = await save_named(db, connector="aws", project_id=workspace_id, actor_id=None, payload={
        "name": "platform", "bound_scopes": [OTHER], "aws_region": "eu-west-1", "allow_platform_credentials": True})
    assert opt_in["fields"]["allow_platform_credentials"] is True
    listed = json.dumps(await list_named(db, connector="aws", project_id=workspace_id))
    assert "fake-secret-key-1" not in listed and "AKIAEXAMPLE" not in listed and "_secret_ref" not in listed


async def test_over_mcp_the_opt_in_is_per_connection_and_audited(db, boto, monkeypatch) -> None:
    for name, entry in EXTRA_GOVERNED_MCP_TOOLS.items():
        monkeypatch.setitem(GOVERNED_MCP_TOOLS, name, entry)
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    await upsert_tool_config(db, tool_name="aws", project_id=workspace_id, config={"aws_region": "eu-central-1"},
                             is_active=True)
    await save_named(db, connector="aws", project_id=workspace_id, actor_id=None, payload={
        "name": "prod", "bound_scopes": [PROD], "aws_region": "eu-west-1", "aws_role_arn": ROLE})
    platform = await save_named(db, connector="aws", project_id=workspace_id, actor_id=None, payload={
        "name": "platform", "bound_scopes": [OTHER], "aws_region": "eu-west-1", "allow_platform_credentials": True})
    await db.commit()
    caller = McpCaller(user_id=member_id, grant_id="grant-1", scopes=("knowledge:read", "knowledge:write"),
                       workspace_header=workspace_id, client_name="claude-code")

    async def run(arguments):
        return await run_governed_mcp_tool(db, caller=caller, tool_name="list_aws_eks_clusters", arguments=arguments)

    async def audits() -> int:
        return len((await db.execute(select(AuditLog).where(
            AuditLog.action == "mcp.connector.platform_credentials_used"))).scalars().all())

    assert (await run({"account_id": PROD}))["clusters"] == ["demo-eks"]
    assert await audits() == 0, "an own role: nothing to audit"
    assert (await run({"connection": "platform"}))["clusters"] == ["demo-eks"]
    assert await audits() == 1, "only the opt-in admitted it: audited"
    row = (await db.execute(select(AuditLog).where(
        AuditLog.action == "mcp.connector.platform_credentials_used"))).scalars().one()
    assert row.details["connection_id"] == platform["id"], "the audit row names the connection the call ran on"
    refused = await run({"connection": "default"})
    assert (refused["state"], refused["reason"]) == ("needs_configuration", "aws_credentials_required")
    assert await audits() == 1


async def test_the_cli_paths_assume_the_configured_role(monkeypatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "HOST-KEY")

    class Frozen:
        access_key, secret_key, token = "ASIA-ASSUMED", "assumed-secret", "assumed-token"

    class Session:
        def get_credentials(self):
            class Credentials:
                def get_frozen_credentials(self):
                    return Frozen()
            return Credentials()

    async def assume(context, session):
        assert context.project_config["aws_role_arn"] == ROLE
        return Session()

    monkeypatch.setattr(aws_core, "_get_boto_session", lambda context: object())
    monkeypatch.setattr(aws_core, "_assume_role_if_needed", assume)
    context = ToolContext(user_id="u", project_ids=["p"], roles=["admin"], session_id="s",
                          project_config={"aws_region": "eu-west-1", "aws_role_arn": ROLE})
    env = await aws_core._aws_env(context)
    assert env["AWS_ACCESS_KEY_ID"] == "ASIA-ASSUMED" and env["AWS_SESSION_TOKEN"] == "assumed-token"
    assert "HOST-KEY" not in env.values()


async def test_the_cli_paths_refuse_when_the_role_yields_no_credentials(monkeypatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "HOST-KEY")

    class Session:
        def get_credentials(self):
            return None  # botocore: no credential resolved

    async def assume(context, session):
        return Session()

    monkeypatch.setattr(aws_core, "_get_boto_session", lambda context: object())
    monkeypatch.setattr(aws_core, "_assume_role_if_needed", assume)
    context = ToolContext(user_id="u", project_ids=["p"], roles=["admin"], session_id="s",
                          project_config={"aws_region": "eu-west-1", "aws_role_arn": ROLE})
    with pytest.raises(ValueError, match="yielded no credentials"):
        await aws_core._aws_env(context)
