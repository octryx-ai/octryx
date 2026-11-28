"""Shared test helpers for the Jira task list: a Server/DC-shaped Jira handler and the Cloud stub behind transports."""

from __future__ import annotations

import json
import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.routes.secure_work.secure_work import router as secure_work_router
from app.api.routes.secure_work.secure_work_intake import router as intake_router
from app.api.routes.secure_work.secure_work_intake_setup import router as intake_setup_router
from app.api.routes.secure_work.secure_work_workflows import router as workflows_router
from app.db import get_db
from app.models import BuiltInToolConfig, Project, Role, User, UserRole
from app.services.auth import get_current_user
from tests import source_stub_support as stubs

cloud_stub = stubs.load("jira_stub_cloud")
CLOUD_URL = "https://your-site.atlassian.net"
DC_URL = "https://jira.example.test"
TRANSITIONS = [{"id": "31", "name": "Start Progress", "to": {"name": "In Progress"}}]


def dc_issue(key: str, *, status: dict | None = None, project: str | None = None) -> dict:
    return {
        "id": f"id-{key}",
        "key": key,
        "fields": {
            "project": {"key": project or key.split("-")[0]},
            "summary": f"DC issue {key}",
            "description": "Line one.\n\nLine two.",
            "status": status or {"name": "Open", "statusCategory": {"key": "new"}},
            "assignee": {"name": "jdoe", "displayName": "Jane Doe"},
            "reporter": {"name": "rroe", "displayName": "Richard Roe"},
            "comment": {"total": 1, "comments": [
                {"id": "900", "author": {"name": "rroe", "displayName": "Richard Roe"},
                 "body": "Please check *this*.", "created": "2026-10-03T08:00:00.000+0200"}]},
            "updated": "2026-10-03T08:00:00.000+0200",
        },
    }


class DcJira:
    def __init__(self, issues: list[dict], *, refuse_jql_with: str | None = None) -> None:
        self.issues = issues
        self.refuse_jql_with = refuse_jql_with
        self.requests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        query = parse_qs(urlsplit(str(request.url)).query)
        self.requests.append({"method": request.method, "path": request.url.path, "query": query, "body": body})
        path = request.url.path
        if path.startswith("/rest/api/3/"):
            return httpx.Response(404, json={"errorMessages": ["not on this server"]})
        if path == "/rest/api/2/search":
            jql = (query.get("jql") or [""])[0]
            if self.refuse_jql_with and self.refuse_jql_with in jql:
                return httpx.Response(400, json={"errorMessages": ["Field 'BROKEN' does not exist."]})
            return httpx.Response(200, json={"startAt": 0, "total": len(self.issues), "issues": self.issues})
        if path.endswith("/transitions") and request.method == "GET":
            return httpx.Response(200, json={"transitions": TRANSITIONS})
        if path.endswith("/transitions") and request.method == "POST":
            return httpx.Response(204)
        if path.startswith("/rest/api/2/issue/") and path.endswith("/comment"):
            return httpx.Response(201, json={"id": "901"})
        if path.startswith("/rest/api/2/issue/") and request.method == "PUT":
            return httpx.Response(204)
        return httpx.Response(404, json={"errorMessages": ["not found"]})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def cloud_transport(seen: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        target = request.url.raw_path.decode()
        seen.append({"method": request.method, "path": request.url.path, "body": body})
        if request.url.path.endswith("/transitions"):
            return httpx.Response(200, json={"transitions": TRANSITIONS}) if request.method == "GET" else httpx.Response(204)
        status, payload = cloud_stub.handle(request.method, target, request.headers.get("Authorization"), body)
        return httpx.Response(status) if status == 204 else httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


def use_transport(monkeypatch, transport: httpx.MockTransport) -> None:
    import app.services.secure_work.jira.jira_connector as connector_module
    import app.services.secure_work.jira.jira_state_sync as state_sync_module
    import app.tools.jira_impl._jira_query_search as search_module

    for module in (connector_module, state_sync_module, search_module):
        monkeypatch.setattr(module, "egress_transport", lambda *_args, **_kwargs: transport)


def cloud_config(allowed: list[str] | None) -> dict:
    config = {"jira_url": CLOUD_URL, "jira_auth_mode": "cloud_api_token", "jira_email": cloud_stub.CLOUD_EMAIL,
              "jira_token": cloud_stub.CLOUD_TOKEN}
    return {**config, "jira_allowed_projects": allowed} if allowed is not None else config


def dc_config(allowed: list[str] | None) -> dict:
    config = {"jira_url": DC_URL, "jira_auth_mode": "basic", "jira_username": "sync", "jira_password": "pw"}
    return {**config, "jira_allowed_projects": allowed} if allowed is not None else config


async def workspace_jira(db, config: dict) -> str:
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    db.add(BuiltInToolConfig(tool_name="jira", project_id=project.id, config=config, is_active=True))
    await db.commit()
    return project.id


@pytest_asyncio.fixture
async def scoped_api(db):
    app = FastAPI()
    app.include_router(workflows_router)
    app.include_router(secure_work_router)
    app.include_router(intake_router)
    app.include_router(intake_setup_router)
    state: dict = {"user": None}

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://wf.test") as api:
        yield api, state


async def _operator(db) -> User:
    role = (await db.execute(select(Role).where(Role.name == "operation"))).scalar_one_or_none()
    if role is None:
        role = Role(name="operation", description="operation")
        db.add(role)
        await db.flush()
    name = f"op-{uuid.uuid4().hex[:6]}"
    user = User(username=name, email=f"{name}@example.test", password_hash="x", display_name=name,
                account_type="human", is_active=True)
    db.add(user)
    await db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    await db.commit()
    return user


__all__ = [
    "CLOUD_URL",
    "DC_URL",
    "DcJira",
    "_operator",
    "cloud_config",
    "cloud_stub",
    "cloud_transport",
    "dc_config",
    "dc_issue",
    "scoped_api",
    "use_transport",
    "workspace_jira",
]
