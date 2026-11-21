"""The Jira stub (``tests/fixtures/source_stubs``) fits the governed Jira connector exactly.

Its fixtures must produce, through the real platform code, exactly what the stub declares. No network:
the stub's pure ``handle`` sits behind an ``httpx.MockTransport``.

- the stub itself: read-only, credential-checked, and only the JQL shapes the platform builds;
- a full Source Sync through ``run_connector`` with the ``releases`` block: the per-item outcomes,
  the release source's product, version and document role ``release_notes``, and a rendering that
  links every readable issue and leaves the security-level issue out;
- the chat's ``jira_release_status`` tool (the one a chat turn calls) answers the fixture status;
- the stubs' request log keeps methods and paths only, and every request the platform sent is GET.
"""

from __future__ import annotations

import base64

import pytest
from sqlalchemy import select

from app.models import BuiltInToolConfig
from app.models.project.knowledge_evidence import KnowledgeRevisionScope, KnowledgeSourceRevision
from app.models.project.knowledge_source_sync import KnowledgeSourceSyncItem
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.sources.sync import http as http_module
from app.services.knowledge.sources.sync import jira_release_status as status_module
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.connections import SourceConnection
from app.services.knowledge.sources.sync.jira import JiraConnector
from app.services.knowledge.sources.sync.jira_release_config import load_release_config
from app.services.knowledge.sources.sync.service import configure_connector
from app.services.knowledge.sources.sync.service_run import run_connector
from app.tools.jira_release_status import JiraReleaseStatusTool
from tests import source_stub_support as stubs
from tests.egress_support import loopback_stub_exemption_fixture  # noqa: F401  (fixture)
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace, tool_context

# Connector targets pass the outbound URL policy (see tests/egress_support.py).
pytestmark = pytest.mark.usefixtures("loopback_stub_exemption_fixture")

fx = stubs.jira_fixtures
stub = stubs.jira_stub
STUB_URL = f"http://{fx.STUB_HOST}:{fx.STUB_PORT}"
AUTH = "Basic " + base64.b64encode(f"{fx.STUB_USERNAME}:{fx.STUB_TOKEN}".encode()).decode()
PROJECT_JQL = 'project in ("OPS") ORDER BY created ASC, key ASC'


def _get(target: str, authorization: str | None = AUTH) -> tuple[int, dict]:
    return stub.handle("GET", target, authorization)


def test_the_jira_stub_is_read_only_credential_checked_and_answers_only_the_platforms_queries() -> None:
    assert stub.handle("POST", "/rest/api/2/issue", AUTH)[0] == 405
    assert _get("/rest/api/2/myself", None)[0] == 401
    assert _get("/rest/api/2/myself")[1]["emailAddress"] == fx.STUB_USERNAME
    assert _get("/rest/api/3/myself")[0] == 404  # Cloud-only; the connection test falls back to v2
    status, first = _get(f"/rest/api/2/search?jql={PROJECT_JQL}&startAt=0&maxResults=4&fields=summary,updated")
    assert status == 200 and first["total"] == 6
    assert [issue["key"] for issue in first["issues"]] == ["OPS-1", "OPS-2", "OPS-3", "OPS-4"]
    assert set(first["issues"][0]["fields"]) == {"summary", "updated"}
    assert _get("/rest/api/2/search?jql=project%20%3D%20OPS&maxResults=5")[0] == 400
    status, versions = _get("/rest/api/2/project/OPS/version?startAt=0&maxResults=1&orderBy=sequence")
    assert status == 200 and [v["name"] for v in versions["values"]] == ["2.4.19"] and versions["isLast"] is False
    assert _get("/rest/api/2/project/OPS/version?startAt=1&maxResults=1")[1]["isLast"] is True
    assert _get("/rest/api/2/project/NOPE/version")[0] == 404


def test_the_request_log_keeps_methods_and_paths_only() -> None:
    log = stubs.stub_http.RequestLog()
    log.record("GET", "/rest/api/2/search")
    log.record("POST", "/rest/api/2/issue")
    assert log.snapshot() == {
        "methods": {"GET": 1, "POST": 1},
        "requests": ["GET /rest/api/2/search", "POST /rest/api/2/issue"],
    }


async def test_the_release_rendering_links_every_readable_issue_and_leaves_the_secured_one_out() -> None:
    connection = SourceConnection(kind="jira", base_url=STUB_URL, principal=fx.STUB_USERNAME, secret=fx.STUB_TOKEN)
    scope = {"project_keys": [fx.PROJECT_KEY], "releases": fx.RELEASES}
    config = validate_config(connector_key="ops-releases", kind="jira", **scope)
    releases = load_release_config(config.scope)
    requests: list[str] = []
    jira = JiraConnector(
        connection,
        project_keys=(fx.PROJECT_KEY,),
        releases=releases,
        transport=stubs.transport(stub, STUB_URL, requests),
    )
    items, token = [], None
    while True:
        page = await jira.list_items(token, limit=50)
        items.extend(page.items)
        if (token := page.next_token) is None:
            break
    release = next(item for item in items if item.title == fx.RELEASE_TITLE)
    text = (await jira.fetch(release)).data.decode()

    assert (release.products, release.version, release.role) == ((fx.PRODUCT,), fx.RELEASE_VERSION, "release_notes")
    assert release.source_url == f"{STUB_URL}/projects/OPS/versions/20020"
    assert all(f"- Jira: {fx.browse_url(STUB_URL, key)}" in text for key in fx.RELEASE_ISSUES)
    assert "OPS-4" not in text and "Credential rotation" not in text
    assert "## Fixes" in text and "## Features" in text
    assert requests and all(line.startswith("GET ") for line in requests)


async def _jira_workspace(db):
    workspace_id = await seed_workspace(db)
    owner_id = await seed_member(db, workspace_id=workspace_id, role="owner", username="jira-owner")
    owner = await authorize_workspace(db, current_user=await fetch_user(db, owner_id), workspace_id=workspace_id)
    tool = {
        "jira_auth_mode": "cloud_api_token",
        "jira_url": STUB_URL,
        "jira_email": fx.STUB_USERNAME,
        "jira_token": fx.STUB_TOKEN,
        "jira_allowed_projects": [fx.PROJECT_KEY],
    }
    db.add(BuiltInToolConfig(tool_name="jira", project_id=workspace_id, config=tool, is_active=True))
    await db.flush()
    config = validate_config(
        connector_key="ops-releases", kind="jira", project_keys=[fx.PROJECT_KEY], releases=fx.RELEASES
    )
    row = await configure_connector(db, authorized=owner, config=config, actor_id=owner_id)
    return owner, owner_id, row


async def test_a_jira_sync_against_the_stub_yields_the_release_the_check_asserts(db) -> None:
    owner, owner_id, row = await _jira_workspace(db)
    runtime, _, evidence_index = build_runtime()

    run = await run_connector(
        db, runtime=runtime, authorized=owner, row=row, actor_id=owner_id, transport=stubs.transport(stub, STUB_URL)
    )

    assert run.state == "completed"
    assert {o["external_id"]: (o["outcome"], o["reason"]) for o in run.outcomes} == fx.SYNC_OUTCOMES
    secured = {issue["id"] for issue in fx.ISSUES if issue["key"] in fx.SECURED_ISSUES}
    assert [o for o in run.outcomes if o["external_id"] in secured and o["title"]] == []
    item = (
        await db.execute(
            select(KnowledgeSourceSyncItem).where(
                KnowledgeSourceSyncItem.connector_id == row.id, KnowledgeSourceSyncItem.external_id == "release-20020"
            )
        )
    ).scalar_one()
    assert item.document_role == "release_notes"
    scope = (
        await db.execute(
            select(KnowledgeRevisionScope)
            .join(KnowledgeSourceRevision, KnowledgeSourceRevision.id == KnowledgeRevisionScope.revision_id)
            .where(KnowledgeSourceRevision.source_id == item.source_id)
        )
    ).scalar_one()
    assert (scope.products, scope.version) == ([fx.PRODUCT], fx.RELEASE_VERSION)


async def test_the_chat_release_status_tool_answers_the_fixture_status(db, monkeypatch) -> None:
    owner, owner_id, _ = await _jira_workspace(db)
    requests: list[str] = []
    stub_transport = stubs.transport(stub, STUB_URL, requests)

    def reader(connection, transport=None):
        # The tool passes no transport; the real reader runs against the stub.
        return http_module.SourceReader(connection, transport=stub_transport)

    monkeypatch.setattr(status_module, "SourceReader", reader)
    context = tool_context(user_id=owner_id, project_id=owner.project_id, project_ids=[owner.project_id], db=db)

    result = await JiraReleaseStatusTool().execute({"product": fx.PRODUCT, "version": fx.RELEASE_VERSION}, context)

    got = {key: result.get(key) for key in fx.EXPECTED_STATUS if key != "open_blockers"}
    got["open_blockers"] = [blocker["key"] for blocker in result["open_blockers"]]
    assert got == fx.EXPECTED_STATUS
    assert [blocker["url"] for blocker in result["open_blockers"]] == [fx.browse_url(STUB_URL, "OPS-2")]
    assert result["source"] == "live Jira query"
    assert requests and all(line.startswith("GET ") for line in requests)
