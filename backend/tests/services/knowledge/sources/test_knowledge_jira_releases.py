"""Jira releases as versioned knowledge, and release status as a live, read-only Jira query
(fake Jira over ``httpx.MockTransport``, no network)."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select

from app.models import BuiltInToolConfig
from app.models.project.knowledge_evidence import KnowledgeRevisionScope, KnowledgeSourceRevisionOrigin
from app.models.project.knowledge_source_sync import (
    KnowledgeSourceConnector,
    KnowledgeSourceSyncItem,
    KnowledgeSourceSyncRun,
)
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.sources.sync import jira_release_status as status_module
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.connections import resolve_connection
from app.services.knowledge.sources.sync.jira import JiraConnector
from app.services.knowledge.sources.sync.jira_release_config import load_release_config, release_version
from app.services.knowledge.sources.sync.jira_release_status import jira_release_status
from app.services.knowledge.sources.sync.service import configure_connector
from app.services.knowledge.sources.sync.service_describe import describe_connector
from app.services.knowledge.sources.sync.service_run import run_connector
from app.services.knowledge.sources.sync.stored_types import PersistedRunReport
from app.services.knowledge.temporal.change_ranking import source_roles
from app.services.knowledge.temporal.versions import in_range, version_key
from app.tools.definitions import get_tool_definition_metadata
from app.tools.jira_release_status import JiraReleaseStatusTool
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace, tool_context
from tests.typed_dict_support import shape_problems

# Connector targets pass the outbound URL policy (see tests/egress_support.py).
pytestmark = pytest.mark.usefixtures("public_source_dns")

JIRA = "https://jira.example.test/jira"
RELEASES = {
    "products": {"OPS": "acme-orders"},
    "version_name_prefixes": ["Release "],
    "sections": [
        {"title": "Breaking changes", "labels": ["breaking-change"]},
        {"title": "New features", "issue_types": ["Story"]},
        {"title": "Bugs fixed", "issue_types": ["Bug"]},
    ],
    "blocker_priorities": ["Blocker"],
}
_FIX_VERSION = re.compile(r'^project = "OPS" AND fixVersion = (\d+) ORDER BY key ASC$')


class FakeJira:
    def __init__(self) -> None:
        self.issues: dict[str, dict] = {}
        self.versions: list[dict] = []
        self.methods: list[str] = []

    def version(self, version_id: str, name: str, *, released: bool, date: str | None = None) -> None:
        entry = {"id": version_id, "name": name, "released": released, "archived": False}
        if date:
            entry["releaseDate"] = date
            entry["description"] = f"Maintenance release {name}."
        self.versions.append(entry)

    def issue(self, number: int, kind: str, summary: str, fix: str, **extra) -> None:
        fields = {
            "summary": summary,
            "description": f"Details of {summary}.",
            "updated": extra.pop("updated", "2026-09-01T10:00:00Z"),
            "issuetype": {"name": kind},
            "status": {"name": extra.pop("status", "Done"), "statusCategory": {"key": extra.pop("category", "done")}},
            "priority": {"name": extra.pop("priority", "Major")},
            "resolution": {"name": "Fixed"},
            "labels": extra.pop("labels", []),
            "fixVersions": [{"id": fix}],
        }
        if extra.pop("security", None):
            fields["security"] = {"id": "1", "name": "Security team"}
        self.issues[str(10000 + number)] = {"id": str(10000 + number), "key": f"OPS-{number}", "fields": fields}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.methods.append(request.method)
        query = parse_qs(urlsplit(str(request.url)).query)
        start, size = int(query["startAt"][0]), int(query["maxResults"][0])
        if request.url.path == "/jira/rest/api/2/project/OPS/version":
            page = self.versions[start : start + size]
            return httpx.Response(200, json={"values": page, "isLast": start + size >= len(self.versions)})
        assert request.url.path == "/jira/rest/api/2/search"
        jql = query["jql"][0]
        ordered = [self.issues[key] for key in sorted(self.issues)]
        match = _FIX_VERSION.match(jql)
        if match:
            ordered = [i for i in ordered if {"id": match.group(1)} in i["fields"]["fixVersions"]]
        else:
            assert jql.startswith('project in ("OPS")')
        return httpx.Response(200, json={"total": len(ordered), "issues": ordered[start : start + size]})


def _fake() -> FakeJira:
    jira = FakeJira()
    jira.version("101", "2.4.19", released=True, date="2026-08-01")
    jira.version("102", "Release 2.4.20", released=False)
    jira.version("103", "Backlog", released=False)
    jira.issue(1, "Story", "Export to PDF", "102", category="indeterminate", status="In Progress")
    jira.issue(2, "Bug", "Login timeout", "102", category="new", status="Open", priority="Blocker")
    jira.issue(3, "Story", "Drop the v1 API", "102", labels=["breaking-change"])
    jira.issue(4, "Bug", "Confidential leak", "102", security=True, category="new", priority="Blocker")
    jira.issue(5, "Bug", "Old crash", "101")
    return jira


async def _setup(db, *, releases=RELEASES):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    tool = {"jira_auth_mode": "basic", "jira_url": JIRA, "jira_username": "sync", "jira_password": "pw", "jira_allowed_projects": ["OPS"]}
    db.add(BuiltInToolConfig(tool_name="jira", project_id=workspace_id, config=tool, is_active=True))
    await db.flush()
    runtime, _, evidence_index = build_runtime()
    config = validate_config(connector_key="ops", kind="jira", project_keys=["OPS"], releases=releases)
    row = await configure_connector(db, authorized=authorized, config=config, actor_id=user_id)
    return authorized, user_id, runtime, row


async def _run(db, setup, jira: FakeJira):
    authorized, user_id, runtime, row = setup
    row = await db.get(KnowledgeSourceConnector, row.id)
    transport = httpx.MockTransport(jira.handler)
    return await run_connector(
        db, runtime=runtime, authorized=authorized, row=row, actor_id=user_id, transport=transport
    )


async def _release_items(db, row_id: str) -> dict[str, KnowledgeSourceSyncItem]:
    items = await db.execute(select(KnowledgeSourceSyncItem).where(KnowledgeSourceSyncItem.connector_id == row_id))
    return {item.external_id: item for item in items.scalars() if item.external_id.startswith("release-")}


async def test_versions_become_release_revisions_with_product_version_role_and_links(db) -> None:
    setup = await _setup(db)
    authorized, _, _, row = setup
    jira = _fake()

    run = await _run(db, setup, jira)

    # 4 readable issues + 2 releases; the restricted issue and the "Backlog" version are skipped.
    assert run.state == "completed" and run.report["created"] == 6 and run.report["skipped"] == 2
    assert {
        "external_id": "release-103",
        "title": None,
        "outcome": "skipped",
        "reason": "version_name_unrecognized",
    } in (run.outcomes)
    assert run.report["release_sync"] == {"state": "active", "products": {"OPS": "acme-orders"}}
    stored = await db.get(KnowledgeSourceSyncRun, run.id, populate_existing=True)
    assert shape_problems(stored.report, PersistedRunReport, "report") == []
    items = await _release_items(db, row.id)
    assert set(items) == {"release-101", "release-102"}
    assert {item.document_role for item in items.values()} == {"release_notes"}
    revision_of = {}
    for scope in (await db.execute(select(KnowledgeRevisionScope))).scalars():
        revision_of[scope.revision_id] = (tuple(scope.products), scope.version)
    origins = {o.source_url: o.revision_id for o in (await db.execute(select(KnowledgeSourceRevisionOrigin))).scalars()}
    assert revision_of[origins[f"{JIRA}/projects/OPS/versions/102"]] == (("acme-orders",), "2.4.20")
    assert revision_of[origins[f"{JIRA}/projects/OPS/versions/101"]] == (("acme-orders",), "2.4.19")
    # Change answers rank the release with release notes, by its connector's explicit role.
    roles = await source_roles(db, authorized.project_id, [items["release-102"].source_id])
    assert roles == {items["release-102"].source_id: "release_notes"}


async def test_the_release_note_has_configured_sections_issue_links_and_no_restricted_issue(db) -> None:
    authorized, _, _, row = await _setup(db)
    jira = _fake()
    connection = await resolve_connection(db, kind="jira", project_id=authorized.project_id)
    connector = JiraConnector(
        connection,
        project_keys=("OPS",),
        releases=load_release_config(dict(row.scope)),
        transport=httpx.MockTransport(jira.handler),
    )

    page = await connector.list_items("r:0:0", limit=50)
    release = next(item for item in page.items if item.external_id == "release-102")
    text = (await connector.fetch(release)).data.decode()

    assert release.title == "Release 2.4.20" and release.acl.audience == "scope"
    assert page.skipped == (("release-103", "version_name_unrecognized"),) and page.next_token is None
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings == ["## Breaking changes", "## New features", "## Bugs fixed"]
    assert f"- Jira: {JIRA}/browse/OPS-3" in text and f"- Jira: {JIRA}/browse/OPS-2" in text
    assert "OPS-4" not in text and "Confidential" not in text
    assert "In Progress" not in text  # status is live-only, never stored knowledge


async def test_an_unchanged_resync_creates_nothing_and_a_changed_issue_one_release_revision(db) -> None:
    setup = await _setup(db)
    jira = _fake()
    await _run(db, setup, jira)

    again = await _run(db, setup, jira)
    jira.issue(2, "Bug", "Login timeout on SSO", "102", updated="2026-09-05T10:00:00Z")
    changed = await _run(db, setup, jira)

    assert again.report["created"] == 0 and again.report["updated"] == 0 and again.report["unchanged"] == 6
    # The issue itself and the one release that lists it; the other release is unchanged.
    assert changed.report["updated"] == 2 and changed.report["unchanged"] == 4
    updated = {o["external_id"] for o in changed.outcomes if o["outcome"] == "updated"}
    assert updated == {"10002", "release-102"}


def test_jira_version_names_normalize_only_by_explicit_data() -> None:
    assert release_version("2.4.20", ()) == "2.4.20"
    assert release_version("v2.4.20", ()) == "2.4.20"
    assert release_version("Release 2.4.20", ()) is None
    assert release_version("Release 2.4.20", ("Release ",)) == "2.4.20"
    assert release_version("Backlog", ("Release ",)) is None
    assert version_key("2.4.3") < version_key("2.4.20") < version_key("2.5.0")
    assert version_key("v2.4.20") == version_key("2.4.20")
    assert in_range("2.4.20", after="2.4.19", through="2.4.20")
    assert not in_range("2.4.19", after="2.4.19", through="2.4.20")


async def test_release_sync_without_a_product_is_needs_configuration(db) -> None:
    setup = await _setup(db, releases={"products": {}})
    jira = _fake()

    run = await _run(db, setup, jira)
    described = await describe_connector(db, await db.get(KnowledgeSourceConnector, setup[3].id))

    expected = {"state": "needs_configuration", "reason": "release_product_not_configured"}
    assert described["release_sync"] == expected and run.report["release_sync"] == expected
    stored = await db.get(KnowledgeSourceSyncRun, run.id, populate_existing=True)
    assert shape_problems(stored.report, PersistedRunReport, "report") == []
    assert await _release_items(db, setup[3].id) == {}


async def test_the_status_is_a_live_read_only_query_with_counts_and_blockers(db, monkeypatch) -> None:
    authorized, user_id, _, _ = await _setup(db)
    jira = _fake()
    transport = httpx.MockTransport(jira.handler)

    status = await jira_release_status(
        db, project_id=authorized.project_id, product="acme-orders", version="2.4.20", transport=transport
    )
    missing = await jira_release_status(
        db, project_id=authorized.project_id, product="acme-orders", version="9.9.9", transport=transport
    )

    assert status["state"] == "ok" and status["released"] is False and status["jira_version"] == "Release 2.4.20"
    # The restricted issue is neither counted nor listed.
    assert status["issue_count"] == 3 and status["issue_listing_complete"] is True
    # A mixed release is "open_work", never something a reader could take for "complete".
    assert status["work_state"] == "open_work" and status["open_issue_count"] == 2
    assert "complete" not in status
    assert status["status_counts"] == {"to_do": 1, "in_progress": 1, "done": 1, "unknown": 0}
    assert status["open_blockers"] == [
        {
            "key": "OPS-2",
            "summary": "Login timeout",
            "priority": "Blocker",
            "status": "Open",
            "url": f"{JIRA}/browse/OPS-2",
        }
    ]
    assert status["version_url"] == f"{JIRA}/projects/OPS/versions/102"
    assert missing["state"] == "not_found" and missing["reason"] == "version_not_found"
    assert set(jira.methods) == {"GET"}

    # Through the tool: a product without a Jira release mapping is needs_configuration, never a guess.
    context = tool_context(
        user_id=user_id, project_id=authorized.project_id, project_ids=[authorized.project_id], db=db
    )
    unmapped = await JiraReleaseStatusTool().execute({"product": "billing", "version": "1.0"}, context)
    assert unmapped["state"] == "needs_configuration" and unmapped["reason"] == "release_product_not_configured"


def test_the_release_and_status_code_can_only_send_get() -> None:
    sync_dir = Path(status_module.__file__).parent
    modules = ["jira.py", "jira_releases.py", "jira_release_status.py", "jira_release_render.py"]
    for name in modules:
        source = (sync_dir / name).read_text(encoding="utf-8")
        assert not re.search(r"\.(post|put|patch|delete|request|stream|send)\(", source), name
    reader = (sync_dir / "http.py").read_text(encoding="utf-8")
    assert re.search(r"\bclient\.get\(", reader)
    assert len(re.findall(r"\.post\(", reader)) == 1 and 'JIRA_SEARCH_JQL_PATH = "/rest/api/3/search/jql"' in reader
    assert not re.search(r"\.(put|patch|delete|request|stream)\(", reader)
    metadata = get_tool_definition_metadata("jira_release_status")
    assert (metadata.risk, metadata.approval_required, metadata.mutates_state) == ("read", False, False)
    assert metadata.connector == "jira"


@pytest.mark.parametrize(
    ("counts", "listing_complete", "work_state"),
    [
        ({"to_do": 1, "in_progress": 0, "done": 3, "unknown": 0}, True, "open_work"),
        ({"to_do": 0, "in_progress": 0, "done": 3, "unknown": 0}, True, "all_done"),
        ({"to_do": 0, "in_progress": 0, "done": 3, "unknown": 0}, False, "listing_truncated"),
        ({"to_do": 0, "in_progress": 0, "done": 0, "unknown": 0}, True, "no_issues"),
        ({"to_do": 0, "in_progress": 0, "done": 2, "unknown": 1}, True, "open_work"),
    ],
)
def test_the_work_state_is_one_closed_value(counts, listing_complete, work_state) -> None:
    from app.services.knowledge.sources.sync.jira_release_status import _work_state

    assert _work_state(counts, listing_complete=listing_complete) == work_state
