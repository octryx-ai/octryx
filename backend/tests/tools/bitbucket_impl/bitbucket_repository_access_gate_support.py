"""Shared helpers for the test_bitbucket_repository_access_gate_* modules."""

from __future__ import annotations

import uuid

from app.models import CodeRepository, ConnectorNamedConnection
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.tools.context import ToolContext
from tests.knowledge_evidence_seed_support import seed_workspace

BASE = "https://bitbucket.example.test/bitbucket"


REPO = f"{BASE}/projects/PROJ/repos/app"


CLONE = f"{BASE}/scm/proj/app.git"


async def _connection(db, tool_config: dict | None = None) -> str:
    row = ConnectorNamedConnection(id=str(uuid.uuid4()), tool_name="bitbucket", project_id=None,
                                   scope_key="global", name=f"bb-{uuid.uuid4().hex[:6]}", bound_scopes=[],
                                   config=tool_config or {"bitbucket_url": BASE}, available_in="all")
    db.add(row)
    await db.flush()
    return row.id


async def _register(db, workspace_id: str, mode: str, *, remote: str = REPO, cloud: bool = False) -> None:
    scope = {"fetch_mode": "remote_git", "remote": remote, "web_base": remote, "ref": "main", "access_mode": mode}
    if not cloud:
        scope |= {"host": "bitbucket_datacenter", "host_base": BASE}
    db.add(KnowledgeSourceConnector(project_id=workspace_id, connector_key=f"repo-{uuid.uuid4().hex[:8]}",
                                    kind="git_repository", connection_id=await _connection(db), scope=scope))
    await db.flush()


async def _workspace(db, *, repo_root: str = "/srv/repos/app", name: str = "PROJ/app") -> str:
    workspace_id = await seed_workspace(db)
    db.add(CodeRepository(project_id=workspace_id, provider="bitbucket", name=name, is_active=True,
                          repo_root=repo_root, remote_url=CLONE,
                          config_json={"operation_policy": {"read": True, "branch": True, "write": True,
                                                            "pr": True}}))
    await db.flush()
    return workspace_id


def _context(db, workspace_id: str, **extra) -> ToolContext:
    config = {"bitbucket_auth_mode": "basic", "bitbucket_url": BASE, "bitbucket_username": "bot", "bitbucket_password": "pw",
              "bitbucket_allowed_repos": [{"project_key": "PROJ", "repo_slug": "app", "enabled": True}]}
    return ToolContext(user_id="u1", project_ids=[workspace_id], roles=[], session_id="s1", project_config=config,
                       db=db, **extra)
