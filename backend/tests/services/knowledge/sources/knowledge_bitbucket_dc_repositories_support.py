"""Shared helpers for the test_knowledge_bitbucket_dc_repositories_* modules."""

from __future__ import annotations

import uuid

from app.models import ConnectionWorkspace, ConnectorNamedConnection
from app.services.named_connections.contract import named_secret_field
from app.services.secret import set_secret_value
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.services.knowledge.sources.knowledge_bitbucket_dc_support import SECRET

BASE = "https://bitbucket.example.test/bitbucket"


IDP = "https://idp.example.test/realms/r/protocol/openid-connect/token"


REPO_URL = f"{BASE}/projects/SHOP/repos/aws-shop-deployment"


FILES = {"README.md": b"# Shop deployment\n\nHelm values for the shop application.\n",
         "deploy/values.yaml": b"replicas: 2\nimage: shop-app\n"}


async def _connection(db, workspaces: list[str], *, url: str = BASE) -> str:
    row = ConnectorNamedConnection(
        id=str(uuid.uuid4()), tool_name="bitbucket", project_id=None, scope_key="global", name="Bitbucket",
        bound_scopes=[], available_in="selected", agent_tools_level="read",
        config={"bitbucket_url": url, "bitbucket_deployment": "datacenter",
                "bitbucket_auth_mode": "oidc_client_credentials", "bitbucket_oidc_token_url": IDP,
                "bitbucket_oidc_client_id": "octryx-client"},
    )
    db.add(row)
    await db.flush()
    for workspace_id in workspaces:
        db.add(ConnectionWorkspace(connection_id=row.id, workspace_id=workspace_id))
    stored = await set_secret_value(db, tool_name="bitbucket", project_id=None, value=SECRET,
                                    field_name=named_secret_field("bitbucket_oidc_client_secret", row.id))
    row.config = {**row.config, "bitbucket_oidc_client_secret_secret_ref": stored.id}
    await db.commit()
    return row.id


async def _author(db, role: str = "admin") -> tuple[str, str]:
    workspace_id = await seed_workspace(db)
    return workspace_id, await seed_member(db, workspace_id=workspace_id, role=role)


def _save_body(connection_id: str, **overrides) -> dict:
    return {"kind": "git_repository", "fetch_mode": "remote_git", "repository_url": REPO_URL, "ref": "main",
            "connection_id": connection_id, **overrides}
