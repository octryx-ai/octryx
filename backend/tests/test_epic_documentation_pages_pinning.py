"""Unattended epic pages stay on the Confluence instance and connection their grant recorded.

Every page call of ``documentation/auto_page_write`` carries ``expected_instance`` and ``expected_connection`` (the
tools refuse anything else before a request, ``test_confluence_instance_guard``), and a Workspace whose Confluence
moved to another instance after the grant writes nothing.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

import app.services.workflow_runs.documentation.auto_page_write as page_write
from app.models import BuiltInToolConfig
from app.services.workflow_runs.documentation.auto_pages import publish_feature
from app.tools._confluence_instance import EXPECTED_CONNECTION_PARAM, EXPECTED_INSTANCE_PARAM, confluence_instance
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.epic_documentation_pages_support import _run, _workspace

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("public_source_dns")]


async def test_every_epic_page_call_is_pinned_to_the_granted_instance_and_connection(db, monkeypatch):
    admin, project, stub, _epic, (s1, _s2) = await _workspace(db, monkeypatch)
    calls: list[tuple[str, dict]] = []
    original = page_write.dispatch_tool

    async def recording(db_, run_, tool, arguments, **kwargs):
        calls.append((tool, dict(arguments)))
        return await original(db_, run_, tool, arguments, **kwargs)

    monkeypatch.setattr(page_write, "dispatch_tool", recording)
    story = _run(admin, project, s1, "epic-delivery", pr="8")
    db.add(story)
    await db.flush()

    assert (await publish_feature(db, story, {}))[1] == "succeeded"
    grant = story.context["documentation_grant"]["target"]
    assert grant["instance"] == confluence_instance(stub.base)
    assert {tool for tool, _arguments in calls} >= {"get_confluence_page", "create_confluence_page"}
    for tool, arguments in calls:
        assert arguments[EXPECTED_INSTANCE_PARAM] == grant["instance"], tool
        assert arguments[EXPECTED_CONNECTION_PARAM] == grant["connection_id"], tool


async def test_a_confluence_moved_to_another_instance_after_the_grant_writes_nothing(db, monkeypatch):
    admin, project, stub, _epic, (s1, s2) = await _workspace(db, monkeypatch)
    story1 = _run(admin, project, s1, "epic-delivery", pr="8")
    db.add(story1)
    await db.flush()
    assert (await publish_feature(db, story1, {}))[1] == "succeeded"
    before = {page_id: page["version"] for page_id, page in stub.pages.items()}

    # The same connection id now points at another Confluence (an admin edited the endpoint).
    config = (await db.execute(select(BuiltInToolConfig).where(
        BuiltInToolConfig.tool_name == "confluence", BuiltInToolConfig.project_id == project.id))).scalar_one()
    config.config = {**config.config, "confluence_url": "https://moved.example.test/wiki"}
    await db.flush()

    story2 = _run(admin, project, s2, "epic-delivery", after=story1, pr="9")
    db.add(story2)
    await db.flush()
    outcome, route = await publish_feature(db, story2, {})
    assert (route, outcome.result["reason"]) == ("skipped", "target_drift")
    assert {page_id: page["version"] for page_id, page in stub.pages.items()} == before
