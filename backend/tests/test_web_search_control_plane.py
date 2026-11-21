"""The governed web search: no scraping, a pinned blocklist, the trusted-source registry, anomaly quarantine.

Contract tests with a fake HTTP client: without a provider nothing is fetched; blocked and untrusted
results never come back; a provider that ignores its restriction is quarantined; the data policy
admits the query; the Workspace's search mode comes from its project row, not the turn config.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Project
from app.models.project.web_trusted_sources import WebTrustedSource
from app.services.web_search import health
from app.services.web_search.blocklist import platform_blocklist
from app.services.web_search.patterns import InvalidSourcePatternError, normalize_pattern, pattern_matches
from app.services.web_search.registry import propose_sources, put_source
from app.services.web_search.service import governed_search
from app.tools.runtime_impl._runtime_web_search_tools import WebSearchTool
from tests.knowledge_evidence_seed_support import seed_workspace


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code, self._payload = status_code, payload

    def json(self):
        return self._payload


class FakeClient:
    """Records every request; answers the provider POST with the configured results."""

    def __init__(self, results: list[dict], status_code: int = 200):
        self.results, self.status_code, self.requests = results, status_code, []

    def __call__(self, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def post(self, url, headers=None, json=None):
        self.requests.append({"url": url, "headers": headers, "json": json})
        return FakeResponse(self.status_code, {"results": self.results})

    async def get(self, *args, **kwargs):  # a scraper would call this
        raise AssertionError("no result page may be scraped")


def _hit(url: str, title: str = "Title") -> dict:
    return {"url": url, "title": title, "content": "snippet"}


@pytest.fixture(autouse=True)
def _provider(monkeypatch):
    for name in ("OCTRYX_WEB_SEARCH_PROVIDER", "EXA_API_KEY", "OCTRYX_WEB_SEARCH_DATA_POLICY_CLASS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    health._quarantine.clear()
    yield
    health._quarantine.clear()


async def _workspace(db, classification: str | None = "internal") -> str:
    workspace_id = await seed_workspace(db)
    if classification:
        project = await db.get(Project, workspace_id)
        project.config = {"data_policy": {"classification": classification}}
        await db.flush()
    return workspace_id


def test_blocklist_and_patterns_refuse_what_they_must():
    blocklist = platform_blocklist()
    assert blocklist.category_of("https://www.pornhub.com/view") == "adult"
    assert blocklist.category_of("https://free-sex.example.com/") == "adult"
    assert blocklist.category_of("https://anything.xxx/") == "adult"
    assert blocklist.category_of("https://www.essex.ac.uk/") is None
    assert blocklist.category_of("https://docs.spring.io/spring-boot/") is None
    for weak in ("github.com", "github.io", "10.0.0.1", "com", "https://user:pw@example.com"):
        with pytest.raises(InvalidSourcePatternError):
            normalize_pattern(weak)
    wiki = normalize_pattern("https://github.com/spring-projects/spring-boot/wiki/")
    assert wiki == "github.com/spring-projects/spring-boot/wiki"
    assert pattern_matches(wiki, "https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0-Migration-Guide")
    assert not pattern_matches(wiki, "https://github.com/spring-projects/spring-boot-evil/wiki")
    assert pattern_matches("spring.io", "https://docs.spring.io/x") and not pattern_matches(
        "spring.io", "https://notspring.io/"
    )


async def test_without_a_provider_search_needs_configuration_and_nothing_is_fetched(db, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY")
    client = FakeClient([])
    outcome = await governed_search(
        db, project_id=await _workspace(db), query="spring boot 4", trusted_only=False, client_factory=client
    )
    assert (outcome.state, outcome.reason) == ("needs_configuration", "provider_not_configured")
    assert client.requests == []


async def test_open_search_drops_blocked_results_and_excludes_blocked_sources_at_the_provider(db):
    workspace_id = await _workspace(db)
    await put_source(db, project_id=workspace_id, pattern="spam.example.com", state="blocked", user_id=None)
    client = FakeClient(
        [_hit("https://docs.spring.io/boot"), _hit("https://www.xvideos.com/v"), _hit("https://spam.example.com/a")]
    )
    outcome = await governed_search(
        db, project_id=workspace_id, query="spring boot 4", trusted_only=False, client_factory=client
    )
    assert outcome.ok and [hit.url for hit in outcome.hits] == ["https://docs.spring.io/boot"]
    assert outcome.dropped["blocked"] == 2
    request = client.requests[0]
    assert request["url"] == "https://api.tavily.com/search"
    assert request["headers"]["Authorization"] == "Bearer tvly-test"
    assert request["json"]["exclude_domains"] == ["spam.example.com"]


async def test_trusted_only_restricts_the_provider_and_enforces_path_prefixes(db):
    workspace_id = await _workspace(db)
    client = FakeClient([])
    outcome = await governed_search(
        db, project_id=workspace_id, query="spring boot 4", trusted_only=True, client_factory=client
    )
    assert (outcome.state, outcome.reason) == ("needs_configuration", "no_trusted_sources") and not client.requests

    await put_source(
        db, project_id=None, pattern="github.com/spring-projects/spring-boot/wiki", state="trusted", user_id=None
    )
    client = FakeClient(
        [
            _hit("https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0-Migration-Guide"),
            _hit("https://github.com/someone-else/spring-boot-4-hacks"),
        ]
    )
    outcome = await governed_search(
        db, project_id=workspace_id, query="spring boot 4", trusted_only=True, client_factory=client
    )
    assert client.requests[0]["json"]["include_domains"] == ["github.com"]
    assert [hit.url for hit in outcome.hits] == [
        "https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0-Migration-Guide"
    ]
    assert outcome.dropped["outside_trusted"] == 1


async def test_a_provider_answering_outside_its_restriction_is_quarantined(db):
    workspace_id = await _workspace(db)
    client = FakeClient([_hit("https://docs.spring.io/a"), _hit("https://games.example.org/")])
    outcome = await governed_search(
        db,
        project_id=workspace_id,
        query="spring boot 4",
        trusted_only=False,
        restrict_to=["spring.io"],
        client_factory=client,
    )
    assert (outcome.state, outcome.reason, outcome.hits) == ("unavailable", "answer_off_restriction", [])
    again = await governed_search(
        db, project_id=workspace_id, query="anything", trusted_only=False, client_factory=FakeClient([])
    )
    assert again.state == "unavailable" and health.quarantine_reason("tavily") == "answer_off_restriction"


async def test_the_data_policy_admits_the_query(db, monkeypatch):
    unclassified = await _workspace(db, classification=None)
    client = FakeClient([_hit("https://docs.spring.io/a")])
    outcome = await governed_search(db, project_id=unclassified, query="q", trusted_only=False, client_factory=client)
    assert outcome.state == "needs_configuration" and not client.requests

    confidential = await _workspace(db, classification="confidential")
    outcome = await governed_search(db, project_id=confidential, query="q", trusted_only=False, client_factory=client)
    assert outcome.state == "denied" and not client.requests


async def test_an_agent_only_proposes_and_never_reopens_an_admin_decision(db):
    workspace_id = await _workspace(db)
    await put_source(db, project_id=None, pattern="blocked.example.com", state="blocked", user_id=None)
    recorded = await propose_sources(
        db,
        project_id=workspace_id,
        proposals=[
            ("docs.spring.io", "https://docs.spring.io/spring-boot/", "entry point", "spring-boot"),
            ("blocked.example.com", "https://blocked.example.com/x", "entry point", None),
            ("github.com", "https://github.com/x", "too broad", None),
        ],
    )
    assert recorded == ["docs.spring.io"]
    rows = (await db.execute(select(WebTrustedSource).where(WebTrustedSource.origin == "agent"))).scalars().all()
    assert [(row.pattern, row.state, row.scope_key) for row in rows] == [("docs.spring.io", "proposed", workspace_id)]


async def test_the_chat_tool_takes_the_search_mode_from_the_project_row(db, monkeypatch):
    workspace_id = await _workspace(db)
    project = await db.get(Project, workspace_id)
    project.config = {**project.config, "web_search_policy": {"mode": "trusted_only"}}
    await db.flush()
    requests: list = []

    async def forbidden(*args, **kwargs):
        requests.append(kwargs)
        return []

    monkeypatch.setattr("app.services.web_search.service.search_provider", forbidden)

    class Context:
        db = None
        session_id = None
        project_ids = [workspace_id]
        # A merged turn config claiming ``open`` must not win over the admin's setting.
        project_config = {"project_id": workspace_id, "web_search_policy": {"mode": "open"}}

    context = Context()
    context.db = db
    result = await WebSearchTool().execute({"query": "spring boot 4"}, context)
    assert result["workspace_search_mode"] == "trusted_only"
    assert (result["state"], result["reason"]) == ("needs_configuration", "no_trusted_sources")
    assert requests == [] and "error" in result
