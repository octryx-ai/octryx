"""``list_confluence_page_updates`` on the Source Sync ledger (open point K5).

Contract tests against a fake Confluence (``httpx.MockTransport``) and the real sync runner: the
feed reports new, changed and removed pages with their titles, page versions, ledger revisions,
recorded times and links; it answers explicit states when there is no Confluence connector or it
never completed a sync; it enforces source ACLs like the governed search; and it has no path to the
retired KnowledgeMap store.
"""

from __future__ import annotations

import ast
import inspect
from datetime import timedelta

import pytest
from sqlalchemy import update

from app.models.project.knowledge_evidence import KnowledgeSourceRevision
from app.models.project.knowledge_source_sync import KnowledgeSourceSyncItem
from app.services.knowledge.access.source_acl import restrict_source
from app.services.knowledge.sources.sync import confluence_updates
from app.services.system_config.constants import DEFAULT_SUMMARY_DOMAIN_SATISFYING_TOOLS
from app.time_utils import utc_now
from app.tools.definitions import get_tool_definition_metadata
from app.tools.knowledge_evidence.confluence_updates import ListConfluencePageUpdatesTool
from app.tools.registry import TOOL_REGISTRY
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace, tool_context
from tests.knowledge_source_sync_support import WIKI, FakeConfluence, _run, _setup

# Connector targets pass the outbound URL policy (see tests/egress_support.py).
pytestmark = pytest.mark.usefixtures("public_source_dns")


class VersionedConfluence(FakeConfluence):
    """The listing reports each page's own version number, so an edit is a new version."""

    def __init__(self) -> None:
        super().__init__()
        self.versions: dict[str, int] = {}

    def handler(self, request):
        response = super().handler(request)
        if request.url.path == "/wiki/rest/api/content":
            payload = response.json()
            for entry in payload["results"]:
                entry["version"] = {"number": self.versions.get(entry["id"], 1)}
            return type(response)(200, json=payload)
        return response


def _tool(db, *, user_id: str, workspace_id: str):
    return tool_context(user_id=user_id, project_id=workspace_id, project_ids=[workspace_id], db=db)


async def test_the_feed_reports_new_changed_and_removed_pages_from_the_ledger(db) -> None:
    setup = await _setup(db, kind="confluence")
    authorized, admin_id, _, _ = setup
    workspace_id = authorized.project_id
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    tool = ListConfluencePageUpdatesTool()
    context = _tool(db, user_id=member_id, workspace_id=workspace_id)

    # Configured but never synced: an explicit state, never "nothing changed".
    never = await tool.execute({}, context)
    assert (never["state"], never["reason"]) == ("needs_configuration", "confluence_sync_never_ran")

    wiki = VersionedConfluence()
    wiki.put("101", "Failover Runbook", "<p>Failover runs from Geneva.</p>")
    wiki.put("102", "Backup Policy", "<p>Backups run nightly.</p>")
    first = await _run(db, setup, wiki)
    assert first.state == "completed"

    fresh = await tool.execute({}, context)
    assert (fresh["state"], fresh["source"], fresh["window_days"]) == ("ok", "Confluence Source Sync ledger", 7)
    assert {page["title"]: page["url"] for page in fresh["new_pages"]} == {
        "Failover Runbook": f"{WIKI}/pages/viewpage.action?pageId=101",
        "Backup Policy": f"{WIKI}/pages/viewpage.action?pageId=102",
    }
    assert {page["current_version"] for page in fresh["new_pages"]} == {1}
    assert (fresh["total_pages"], fresh["changed_count"], fresh["removed_count"]) == (2, 0, 0)
    assert fresh["synced_through"] and fresh["last_sync_complete"] is True

    # A month later: page 101 was edited, page 102 was deleted in Confluence.
    month_ago = utc_now() - timedelta(days=30)
    await db.execute(
        update(KnowledgeSourceRevision)
        .where(KnowledgeSourceRevision.project_id == workspace_id)
        .values(created_at=month_ago)
    )
    await db.execute(
        update(KnowledgeSourceSyncItem)
        .where(KnowledgeSourceSyncItem.project_id == workspace_id)
        .values(updated_at=month_ago)
    )
    wiki.put("101", "Failover Runbook", "<p>Failover runs from Lugano.</p>")
    wiki.versions["101"] = 2
    del wiki.pages["102"]
    second = await _run(db, setup, wiki)
    assert second.state == "completed"

    feed = await tool.execute({"days": 7}, context)
    assert feed["new_pages"] == []
    [changed] = feed["changed_pages"]
    assert (changed["id"], changed["title"], changed["current_version"], changed["revision"]) == (
        "101",
        "Failover Runbook",
        2,
        2,
    )
    assert changed["url"] == f"{WIKI}/pages/viewpage.action?pageId=101" and changed["recorded_at"]
    assert [(page["id"], page["title"]) for page in feed["removed_pages"]] == [("102", "Backup Policy")]
    assert (feed["total_pages"], feed["unchanged_count"]) == (1, 0)
    # A wider window reaches back to the first sync, but a page counts once.
    assert (await tool.execute({"days": 60}, context))["new_count"] == 1

    # Source ACLs are enforced exactly as in the governed search: a restricted page is invisible.
    await restrict_source(
        db, project_id=workspace_id, source_key="confluence.ops.101", restriction="page", member_emails=()
    )
    restricted = await tool.execute({"days": 60}, context)
    assert restricted["new_pages"] == [] and restricted["changed_pages"] == [] and restricted["total_pages"] == 0

    # Bounds are explicit, and the Workspace is the run's: an argument cannot choose another one.
    assert (await tool.execute({"days": 0}, context))["state"] == "invalid_request"
    assert (await tool.execute({"limit": 500}, context))["state"] == "invalid_request"
    other_id = await seed_workspace(db)
    other = await tool.execute({"project_id": workspace_id}, _tool(db, user_id=admin_id, workspace_id=other_id))
    assert other["state"] == "not_found"


async def test_no_connector_is_needs_configuration_and_there_is_no_legacy_path(db) -> None:
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")

    answer = await ListConfluencePageUpdatesTool().execute({}, _tool(db, user_id=member_id, workspace_id=workspace_id))

    assert (answer["state"], answer["reason"]) == ("needs_configuration", "confluence_sync_not_configured")
    assert "error" in answer
    # The feed reads only Source Sync and ledger models; nothing it imports names the retired store.
    tree = ast.parse(inspect.getsource(confluence_updates))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
    assert imported and not {name for name in imported if "KnowledgeMap" in name or "knowledge_map" in name}
    assert not any(isinstance(node, ast.Constant) and node.value == "confluence-sync" for node in ast.walk(tree))
    # A registered built-in read of the Workspace ledger, and it satisfies the Confluence summary domain.
    assert "list_confluence_page_updates" in TOOL_REGISTRY
    metadata = get_tool_definition_metadata("list_confluence_page_updates")
    assert (metadata.risk, metadata.owner_type, metadata.mutates_state) == ("read", "built_in", False)
    assert "list_confluence_page_updates" in DEFAULT_SUMMARY_DOMAIN_SATISFYING_TOOLS["confluence"]
