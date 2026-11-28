"""Source Sync applies the connection's Confluence page allowlist like the tools."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import BuiltInToolConfig
from app.models.project.knowledge_source_sync import KnowledgeSourceSyncItem
from app.services.knowledge.sources.sync.connections import connection_from_config
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_source_sync_support import WIKI, _setup
from tests.services.knowledge.sources.test_confluence_cloud_freshness import _cloud
from tests.support.confluence_cloud_freshness_corrections_support import _run

pytestmark = pytest.mark.usefixtures("public_source_dns")


def _space(stub) -> None:
    stub.put("1", "Home", "<p>Home.</p>")
    stub.put("10", "Page1", "<p>1</p>", parent="1")
    stub.put("20", "Page2", "<p>2</p>", parent="10")
    stub.put("21", "Page2.1", "<p>2.1</p>", parent="20")
    stub.put("30", "Page3", "<p>3</p>", parent="10")
    stub.put("31", "Page3.1", "<p>3.1</p>", parent="30")
    stub.put("32", "Page3.2", "<p>3.2</p>", parent="30")
    stub.put("33", "Page3.2.1", "<p>3.2.1</p>", parent="32")


async def _set_pages(db, setup, rules) -> None:
    entry = (await db.execute(select(BuiltInToolConfig).where(
        BuiltInToolConfig.tool_name == "confluence", BuiltInToolConfig.project_id == setup[0].project_id,
    ))).scalar_one()
    entry.config = {**entry.config, "confluence_allowed_pages": rules}
    await db.flush()


async def _states(db, setup) -> dict[str, str]:
    rows = await db.execute(select(KnowledgeSourceSyncItem.external_id, KnowledgeSourceSyncItem.state).where(
        KnowledgeSourceSyncItem.connector_id == setup[3].id))
    return dict(rows.all())


SUBTREE = {"id": "10", "space_key": "ENG", "enabled": True, "include_children": True, "excludes": ["30"]}
AGAIN = {"id": "32", "space_key": "ENG", "enabled": True, "include_children": True}


async def test_a_space_connector_reads_only_the_allowed_pages_and_retires_what_the_rules_drop(db) -> None:
    setup = await _setup(db, kind="confluence")
    await _set_pages(db, setup, [SUBTREE, AGAIN])
    stub = _cloud()
    _space(stub)

    first = await _run(db, setup, stub)
    assert first.state == "completed"
    assert set(await _states(db, setup)) == {"10", "20", "21", "32", "33"}
    assert first.report["listed"] == 5

    await _set_pages(db, setup, [{**SUBTREE, "excludes": ["20", "30"]}, AGAIN])
    second = await _run(db, setup, stub)
    states = await _states(db, setup)
    assert second.report["retired"] == 2
    assert (states["20"], states["21"], states["10"], states["33"]) == ("retired", "retired", "ingested", "ingested")


async def test_a_whole_space_entry_with_an_exclude_and_no_page_rules_at_all(db) -> None:
    setup = await _setup(db, kind="confluence")
    await _set_pages(db, setup, [{"space_key": "ENG", "whole_space": True, "enabled": True, "excludes": ["30"]}])
    stub = _cloud()
    _space(stub)
    await _run(db, setup, stub)
    assert set(await _states(db, setup)) == {"1", "10", "20", "21"}

    await _set_pages(db, setup, [])
    await _run(db, setup, stub)
    assert {key for key, state in (await _states(db, setup)).items() if state == "ingested"} == set(
        ["1", "10", "20", "21", "30", "31", "32", "33"]), "no page rules: the whole space"


async def test_page_rules_of_another_space_leave_nothing_of_this_space(db) -> None:
    setup = await _setup(db, kind="confluence")
    await _set_pages(db, setup, [{"id": "900", "space_key": "OTHER", "enabled": True, "include_children": True}])
    stub = _cloud()
    _space(stub)
    run = await _run(db, setup, stub)
    assert run.report["listed"] == 0 and await _states(db, setup) == {}


def test_the_connection_carries_the_page_rules_of_its_config() -> None:
    config = {"confluence_auth_mode": "basic", "confluence_url": WIKI, "confluence_username": "svc", "confluence_password": "pw",
              "confluence_allowed_spaces": [{"space_key": "ENG"}], "confluence_allowed_pages": [SUBTREE]}
    connection = connection_from_config("confluence", config)
    assert [rule.page_id for rule in connection.page_rules] == ["10"]
    assert connection.page_rules[0].excludes == frozenset({"30"})
    assert connection_from_config("jira", {"jira_auth_mode": "basic", "jira_url": "https://jira.example.test", "jira_username": "svc",
                                           "jira_password": "pw", "confluence_allowed_pages": [SUBTREE]}).page_rules == ()
