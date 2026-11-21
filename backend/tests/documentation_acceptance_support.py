"""The documentation phase's systems for an acceptance run: a writable Confluence Cloud stub, the Workspace's
documentation settings and Confluence connection, and its Knowledge source that syncs the documentation space.

Everything runs through the product's own code: the governed Confluence tools (named-connection routing by space,
egress replaced by the stub's transport), the Source Sync's ``run_connector`` against the same stub, the ledger.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json

import httpx
from sqlalchemy import select

from app.models import BuiltInToolConfig, Project, User
from app.models.security.user import UserProject
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.service import configure_connector
from tests import source_stub_support as stubs
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_source_sync_support import StubParser

ORIGIN = "https://docs.example.test"
SPACE = "DOCS"
PARENT = "900"
CONFLUENCE_TOOLS = ["create_confluence_page", "update_confluence_page", "get_confluence_page"]


def stub_transport(stub) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        status, payload, headers = stub.handle(request.method, request.url.raw_path.decode(),
                                               request.headers.get("Authorization"), body)
        return httpx.Response(status, json=payload, headers=headers)

    return httpx.MockTransport(handler)


async def documentation_systems(db, project: Project, monkeypatch, *, requester: User):
    """The stub (``writable``, the parent page ``900``) wired behind the Workspace's Confluence and Knowledge."""
    import app.tools._confluence_access as confluence_access
    from app.services.workflow_runs.documentation import knowledge

    stub = stubs.confluence_stub.CloudConfluence(ORIGIN, space=SPACE, principal="docs-bot", secret="docs-pw")
    stub.writable = True
    stub.put(PARENT, "Feature documentation", "<p>Index of the features.</p>")
    transport = stub_transport(stub)
    monkeypatch.setattr(confluence_access, "egress_transport", lambda _connection: transport)
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=project.id, is_active=True, config={
        "confluence_auth_mode": "basic",
        "confluence_url": stub.base, "confluence_username": "docs-bot", "confluence_password": "docs-pw",
        "confluence_allowed_spaces": [{"space_key": SPACE, "enabled": True}]}))
    policy = dict(project.config.get("tool_policy") or {})
    project.config = {**project.config,
                      "feature_documentation": {"confluence_space_key": SPACE, "parent_page_id": PARENT},
                      "tool_policy": {**policy, "allowlist": [*policy.get("allowlist", []), *CONFLUENCE_TOOLS]}}
    member = (await db.execute(select(UserProject).where(UserProject.user_id == requester.id,
                                                         UserProject.project_id == project.id))).scalar_one_or_none()
    if member is None:
        db.add(UserProject(user_id=requester.id, project_id=project.id, role="admin", granted_by=requester.id))
    await db.flush()
    authorized = await authorize_workspace(db, current_user=requester, workspace_id=project.id, require_author=True)
    runtime, _s3, evidence_index = build_runtime()
    runtime = dataclasses.replace(runtime, parser=StubParser())
    config = validate_config(connector_key="docs", kind="confluence", products=["payments"], max_items_per_run=100,
                             spaces=[SPACE])
    source = await configure_connector(db, authorized=authorized, config=config, actor_id=requester.id)
    monkeypatch.setattr(knowledge, "evidence_runtime", lambda: runtime)
    monkeypatch.setattr(knowledge, "sync_transport", lambda: transport)
    # The test database is one connection with savepoints: the sync's "own" session is the shared one here (in
    # production ``source_sync_session`` opens a separate one; the release/resume contract is the same).
    monkeypatch.setattr(knowledge, "source_sync_session", lambda: shared_session(db))
    await db.commit()
    return stub, source


@contextlib.asynccontextmanager
async def shared_session(db):
    yield db


DOCUMENTATION = {
    "title": "Totals round half up and the two percent fee",
    "what": "Invoice totals round half up, and every payment carries a two percent fee.",
    "why": "Rounding down under-charged customers on half amounts; the fee covers the card provider's cost.",
    "how_to_use": "Nothing to configure: totals and fees apply to every new invoice after the release.",
}
