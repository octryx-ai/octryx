"""Shared helpers for the test_knowledge_source_sync_* modules."""

from __future__ import annotations

import dataclasses
from urllib.parse import parse_qs, urlsplit

import httpx
from sqlalchemy import func, select

from app.models import BuiltInToolConfig
from app.models.project.knowledge_evidence import KnowledgeSourceRevision
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ingestion.parser_port import ParserIdentity
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.service import configure_connector
from app.services.knowledge.sources.sync.service_run import run_connector
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace

JIRA = "https://jira.example.test/jira"


WIKI = "https://wiki.example.test/wiki"


def _json(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


class FakeJira:
    """``GET /rest/api/2/search`` over an in-memory project; refuses every other method."""

    def __init__(self) -> None:
        self.issues: dict[str, dict] = {}

    def put(self, issue_id: str, key: str, summary: str, text: str, updated: str, *, security=None) -> None:
        fields = {"summary": summary, "description": text, "updated": updated, "status": {"name": "Open"}}
        if security:
            fields["security"] = {"id": "1", "name": security}
        self.issues[issue_id] = {"id": issue_id, "key": key, "fields": fields}

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.url.path == "/jira/rest/api/2/search"
        query = parse_qs(urlsplit(str(request.url)).query)
        assert query["jql"][0].startswith('project in ("OPS")')
        start, size = int(query["startAt"][0]), int(query["maxResults"][0])
        ordered = [self.issues[key] for key in sorted(self.issues)]
        return _json({"startAt": start, "total": len(ordered), "issues": ordered[start : start + size]})


class FakeConfluence:
    """One space listing, page bodies, and read-restriction lookups for ancestors."""

    def __init__(self) -> None:
        self.pages: dict[str, dict] = {}
        self.broken_bodies: set[str] = set()

    def put(self, page_id: str, title: str, body: str, *, restricted_to=(), ancestors=()) -> None:
        self.pages[page_id] = {"title": title, "body": body, "users": list(restricted_to), "ancestors": list(ancestors)}

    def _restrictions(self, page: dict) -> dict:
        users = [{"username": name} for name in page["users"]]
        return {"restrictions": {"user": {"results": users}, "group": {"results": []}}}

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        path = request.url.path.removeprefix("/wiki/rest/api/content")
        if path == "":
            listing = [
                {
                    "id": page_id,
                    "title": page["title"],
                    "version": {"number": 1},
                    "ancestors": [{"id": item} for item in page["ancestors"]],
                    "restrictions": {"read": self._restrictions(page)},
                }
                for page_id, page in sorted(self.pages.items())
            ]
            return _json({"results": listing, "_links": {}})
        if path.endswith("/restriction/byOperation/read"):
            return _json(self._restrictions(self.pages[path.split("/")[1]]))
        page_id = path.strip("/")
        if page_id in self.broken_bodies:
            return _json({}, status=500)
        return _json({"id": page_id, "body": {"view": {"value": self.pages[page_id]["body"]}}})


class StubParser:
    """Only the identity is needed: sandboxed revisions are registered, parsed later by the worker."""

    identity = ParserIdentity(name="docling-serve", version="1.35.0+p1", sandbox="no_network_uds")


async def _setup(db, *, kind: str, max_items: int = 100):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    if kind == "jira":
        tool = {"jira_auth_mode": "basic", "jira_url": JIRA, "jira_username": "sync", "jira_password": "pw", "jira_allowed_projects": ["OPS"]}
        scope = {"project_keys": ["OPS"]}
    else:
        tool = {
            "confluence_auth_mode": "basic",
            "confluence_url": WIKI,
            "confluence_username": "sync",
            "confluence_password": "pw",
            "confluence_allowed_spaces": [{"space_key": "ENG", "enabled": True}],
        }
        scope = {"spaces": ["ENG"]}
    db.add(BuiltInToolConfig(tool_name=kind, project_id=workspace_id, config=tool, is_active=True))
    await db.flush()
    runtime, _, evidence_index = build_runtime()
    if kind == "confluence":
        runtime = dataclasses.replace(runtime, parser=StubParser())
    config = validate_config(
        connector_key="ops", kind=kind, products=["acme-orders"], max_items_per_run=max_items, **scope
    )
    row = await configure_connector(db, authorized=authorized, config=config, actor_id=user_id)
    return authorized, user_id, runtime, row


async def _run(db, setup, fake):
    authorized, user_id, runtime, row = setup
    row = await db.get(KnowledgeSourceConnector, row.id)
    transport = httpx.MockTransport(fake.handler)
    return await run_connector(
        db, runtime=runtime, authorized=authorized, row=row, actor_id=user_id, transport=transport
    )


async def _count_revisions(db, project_id: str) -> int:
    statement = select(func.count()).select_from(KnowledgeSourceRevision)
    return (await db.execute(statement.where(KnowledgeSourceRevision.project_id == project_id))).scalar_one()


def _counts(run) -> dict:
    return {key: run.report[key] for key in ("created", "updated", "unchanged", "retired", "skipped", "failed")}
