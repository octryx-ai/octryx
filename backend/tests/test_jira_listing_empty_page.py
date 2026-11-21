"""An empty Jira issue page while the source says more remain.

The listing can neither page on (an empty page that keeps a token could loop) nor end: an ended listing
completes the pass, and the runner then retires every served issue the pass did not list as
``removed_at_source``. The page is a contract violation: the run fails and nothing is retired.
Malformed ``labels`` never fail the rendering of an issue.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.models.project.knowledge_source_sync import KnowledgeSourceSyncItem
from app.services.knowledge.sources.sync import runner
from app.services.knowledge.sources.sync.contract import REASON_SOURCE_CONTRACT_VIOLATION, ConnectorError
from app.services.knowledge.sources.sync.jira import JiraConnector
from app.services.knowledge.sources.sync.jira_render import render_issue
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_source_sync_support import FakeJira, _json, _run, _setup
from tests.test_jira_cloud_source_sync import CLOUD, _connection

pytestmark = pytest.mark.usefixtures("public_source_dns")


def _empty_page_while_more_remain(cloud: bool) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if cloud:
            return httpx.Response(200, json={"issues": [], "nextPageToken": "page-0", "isLast": False})
        return httpx.Response(200, json={"issues": [], "startAt": 0, "maxResults": 50, "total": 4})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
@pytest.mark.parametrize(("base_url", "cloud"), [(CLOUD, True), ("https://jira.example.test", False)])
async def test_the_listing_refuses_an_empty_page_while_more_remain(base_url, cloud):
    connector = JiraConnector(_connection(base_url), project_keys=("OPS",), transport=_empty_page_while_more_remain(cloud))

    with pytest.raises(ConnectorError) as refused:
        await connector.list_items(None, limit=50)

    assert refused.value.reason == REASON_SOURCE_CONTRACT_VIOLATION


class _JiraWithAnEmptySecondPage(FakeJira):
    """Answers the first page, then an empty page while ``total`` still says more remain."""

    def handler(self, request: httpx.Request) -> httpx.Response:
        if "startAt=0" not in str(request.url):
            return _json({"startAt": 1, "total": len(self.issues), "issues": []})
        return super().handler(request)


async def test_the_run_fails_and_no_unlisted_issue_is_retired(db, monkeypatch) -> None:
    monkeypatch.setattr(runner, "PAGE_SIZE", 1)
    setup = await _setup(db, kind="jira")
    jira = FakeJira()
    for number in (1, 2, 3):
        jira.put(f"1000{number}", f"OPS-{number}", f"Issue {number}", f"Body {number}.", "2026-09-01T10:00:00Z")
    assert (await _run(db, setup, jira)).state == "completed"
    broken = _JiraWithAnEmptySecondPage()
    broken.issues = jira.issues

    run = await _run(db, setup, broken)

    assert (run.state, run.reason) == ("failed", REASON_SOURCE_CONTRACT_VIOLATION)
    assert run.report["retired"] == 0
    states = (await db.execute(select(KnowledgeSourceSyncItem.state).where(
        KnowledgeSourceSyncItem.connector_id == setup[3].id))).scalars().all()
    assert sorted(states) == ["ingested"] * 3


@pytest.mark.parametrize("labels", [5, "ops", {"name": "ops"}, None, [None, 7, {"x": 1}, "ops"]])
def test_malformed_labels_never_fail_the_rendering(labels):
    rendered = render_issue("OPS-1", {"summary": "Labelled", "labels": labels})

    assert rendered.startswith("# OPS-1: Labelled")
    assert ("- Labels: 7, ops" in rendered) is isinstance(labels, list)
