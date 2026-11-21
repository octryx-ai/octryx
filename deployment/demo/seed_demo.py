"""The demo: everything a first click-through needs, on a fresh install (idempotent).

Run by the compose service ``demo`` (``docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d``) inside
the API image, after the API is healthy and the fake GitHub (service ``demo-git``, ``fake_github.py``) answers. It
adds, through the platform's own models and HTTP API:

- the Workspace "Demo Shop" (Knowledge on, classification ``internal``);
- the repository ``demo/demo-shop`` on the fake GitHub: the small app in ``demo-shop/`` (a known bug, its tests,
  its docs);
- the Demo Shop's README and docs as Knowledge of the Workspace (the same files the repository holds; no internet);
- the GitHub connection "GitHub (demo)" to that fake, available in the Workspace and tested;
- the Workspace's run repository ``demo/demo-shop`` with its test command, so a run can work in it;
- the PR review bot on that repository (trigger ``sync``, status ``inform``);
- two work items, OCX-1 (a small bug) and OCX-2 (a story);
- with ``OCTRYX_DEMO_DIR`` set (the developer stack), the non-admin member ``demo.member``, its login written to
  ``<OCTRYX_DEMO_DIR>/CREDENTIALS.txt`` (0600).

Fail closed: without ``OCTRYX_DEMO=1`` (set only on the ``demo`` service of ``docker-compose.demo.yml``) it changes nothing
and signs nothing. It acts as the ``admin`` account with a 15-minute token it signs itself (it runs in the API image
with the deployment secrets, so it needs no password, also before the first-start setup); the token stays in memory
and is never printed. It prints no secret.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from pathlib import Path
from typing import Any

BACKEND = Path(os.environ.get("OCTRYX_BACKEND_DIR", "/app/backend"))
API_BASE = os.environ.get("OCTRYX_API_BASE", "http://127.0.0.1:8000").rstrip("/")
PANEL = "/admin/chat/api/panel"
GIT_PORT = os.environ.get("OCTRYX_DEMO_GIT_PORT", "8434")
GIT_BASE = f"http://127.0.0.1:{GIT_PORT}"  # the same address in the pod and on the host (docker-compose.yml)
WORKSPACE = os.environ.get("OCTRYX_DEMO_WORKSPACE") or "Demo Shop"
WORKSPACE_DESCRIPTION = "Demo Workspace: the Demo Shop sample app on a local fake GitHub (local demo, not for production)."
OWNER, REPO = "demo", "demo-shop"
REPOSITORY = f"{OWNER}/{REPO}"
CONNECTION = "GitHub (demo)"
KEY_PREFIX = "OCX"
# The fake GitHub accepts any token; this is a placeholder, not a credential of anything.
FAKE_TOKEN = "demo-placeholder-token"
TEST_COMMAND = "python3 -m unittest discover -s tests"
CONTENT = Path(__file__).resolve().parent / "demo-shop"
# The sample run (backend/scripts/run_bundle.py): a real run recorded elsewhere, imported as a sample when present.
SAMPLE_RUN = Path(__file__).resolve().parent / "sample-run" / "run.json"
KNOWLEDGE_FILES = ("README.md", "docs/")
MEMBER = "demo.member"
MEMBER_HEADING = "## Member (no admin role)"
TOKEN_MINUTES = 15
ITEMS = [
    {"title": "Order total takes the discount as an amount", "issue_type": "bug", "labels": ["demo"],
     # Labelled like a good bug report, so the bug workflow's intake check finds everything and asks nothing
     # (workflow_runs/bugs/intake.py: steps, expected, actual, environment).
     "description": ("`order_total` in `shop/pricing.py` subtracts the discount percentage as an amount.\n\n"
                     "Steps: call `order_total([Line(\"mug\", 50.00)], discount_percent=10)`.\n"
                     "Expected: 45.00 (10 % of 50.00 is 5.00).\n"
                     "Actual: 40.00.\n"
                     f"Environment: Python 3 (standard library only); tests: `{TEST_COMMAND}`.")},
    {"title": "Free shipping from 50.00", "issue_type": "story", "labels": ["demo"],
     "description": ("As a customer I pay no shipping when my order is 50.00 or more after the discount.\n\n"
                     "Acceptance: below 50.00 the shipping fee is 4.90; from 50.00 it is 0; the fee is added to the "
                     "order total and shown as its own line.")},
]


def files() -> dict[str, str]:
    """The Demo Shop's files, as the repository on the fake GitHub holds them."""
    return {path.relative_to(CONTENT).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted(CONTENT.rglob("*")) if path.is_file() and "__pycache__" not in path.parts}


def knowledge_files() -> dict[str, str]:
    """The README and the docs: what the Workspace's Knowledge holds of the Demo Shop."""
    return {name: text for name, text in files().items()
            if name.endswith(".md") and any(name == item or name.startswith(item) for item in KNOWLEDGE_FILES)}


def source_key(name: str) -> str:
    """The Knowledge source key of one Demo Shop file (lower case, ``[a-z0-9._-]``): ``demo-shop-docs-onboarding.md``."""
    return "demo-shop-" + name.lower().replace("/", "-")


class Api:
    """The platform's HTTP API as one account (a bearer token)."""

    def __init__(self, token: str = "") -> None:
        self.token = token

    def wait_healthy(self, seconds: int = 300) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{API_BASE}/api/v1/health", timeout=5) as resp:
                    if resp.status == 200:
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(2)
        raise SystemExit(f"demo: the API at {API_BASE} is not healthy after {seconds}s")

    def login(self, username: str, password: str) -> None:
        data = urllib.parse.urlencode({"username": username, "password": password}).encode()
        req = urllib.request.Request(f"{API_BASE}/api/v1/auth/login", data=data, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            self.token = json.loads(resp.read())["access_token"]

    def call(self, method: str, path: str, body: Any = None, ok: tuple[int, ...] = (200, 201, 204)) -> Any:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f"{API_BASE}{path}", data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as err:
            status, raw = err.code, err.read()
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = raw.decode("utf-8", "replace")[:500]
        if ok and status not in ok:
            raise SystemExit(f"demo: {method} {path} -> HTTP {status}: {json.dumps(payload)[:600]}")
        return payload


# ── In-process: the platform's own models (API image only) ──

def _backend() -> None:
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))


def demo_switched_on() -> bool:
    """The one switch: ``OCTRYX_DEMO=1``, set only by the demo's own compose service."""
    return os.environ.get("OCTRYX_DEMO") == "1"


def refuse_production() -> None:
    """The demo seeds only a non-production runtime (the same profiles the platform's loopback exemption and the
    sample run import accept); a production-like profile stops it before anything is written."""
    _backend()
    from app.config import get_settings
    from app.four_eyes_dev_policy import DEV_SELF_APPROVAL_PROFILES

    profile = str(get_settings().runtime_profile or "").strip().lower()
    if profile not in DEV_SELF_APPROVAL_PROFILES:
        raise SystemExit(f"demo: refusing to seed the runtime profile '{profile}' (a local demo, not for production)")


async def _admin_token() -> str:
    """A short-lived token of the ``admin`` account, signed with the deployment's own secret.

    Fail closed: only with the demo switch on. The token lives in memory only; it is never printed or written.
    """
    if not demo_switched_on():
        raise SystemExit("demo: refusing to sign an admin token outside the demo (OCTRYX_DEMO is not 1)")
    _backend()
    from sqlalchemy import select

    from app.db import async_session_factory
    from app.models import User
    from app.services.auth.tokens import create_access_token

    async with async_session_factory() as db:
        admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one_or_none()
    if admin is None:
        raise SystemExit("demo: no admin account yet (the API seeds it on its first start)")
    return create_access_token(admin.id, expires_delta=timedelta(minutes=TOKEN_MINUTES))


async def _knowledge(workspace_id: str) -> None:
    """Knowledge on, classification ``internal``, the README and docs as sources (idempotent by source key)."""
    _backend()
    from sqlalchemy import select

    from app.db import async_session_factory
    from app.models import Project, User
    from app.services.knowledge.access.authorization import authorize_workspace
    from app.services.knowledge.ingestion.text_ingest import ingest_text_source
    from app.services.knowledge.projection.workspace_classification_default import set_workspace_classification
    from app.services.knowledge.projection.workspace_knowledge_state import ensure_knowledge_enabled
    from app.services.knowledge.ledger.errors import EvidenceStoreNotConfiguredError
    from app.services.knowledge.runtime import get_evidence_runtime

    try:
        runtime = get_evidence_runtime()
    except EvidenceStoreNotConfiguredError:
        print("knowledge: this stack has no usable Knowledge object store, the Demo Shop docs are skipped")
        return
    async with async_session_factory() as db:
        admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
        project = (await db.execute(select(Project).where(Project.id == workspace_id))).scalar_one()
        if not ((project.config or {}).get("data_policy") or {}).get("classification"):
            await set_workspace_classification(db, project=project, classification="internal", actor_id=admin.id)
            await db.commit()
        authorized = await authorize_workspace(db, current_user=admin, workspace_id=workspace_id, require_author=True)
        state = await ensure_knowledge_enabled(db, authorized=authorized, actor_id=admin.id)
        print(f"knowledge: {state.get('state')}")
        created = 0
        for name, text in knowledge_files().items():
            result = await ingest_text_source(
                db, runtime=runtime, authorized=authorized, source_key=source_key(name),
                display_title=f"Demo Shop: {name}", declared_media_type="text/markdown",
                data=text.encode("utf-8"), created_by=admin.id,
                source_url=f"{GIT_BASE}/{REPOSITORY}/blob/main/{name}",
            )
            created += int(bool(getattr(result, "created", False)))
        print(f"knowledge: {len(knowledge_files())} Demo Shop documents ({created} new)")


# ── Through the HTTP API, as a person would ──

def seed_workspace(api: Api) -> str:
    projects = api.call("GET", "/api/v1/projects") or []
    ws = next((p for p in projects if p.get("name") == WORKSPACE), None)
    if ws is None:
        ws = api.call("POST", "/api/v1/projects", {"name": WORKSPACE, "description": WORKSPACE_DESCRIPTION})
        print(f"workspace: {WORKSPACE} created")
    else:
        print(f"workspace: {WORKSPACE} present")
    return str(ws["id"])


def seed_git() -> None:
    """The repository on the fake GitHub (its own seed endpoint; an existing repository stays as it is)."""
    req = urllib.request.Request(f"{GIT_BASE}/_fake/repos", method="POST",
                                 data=json.dumps({"owner": OWNER, "repo": REPO, "files": files()}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        created = json.loads(resp.read()).get("created")
    print(f"git: {REPOSITORY} {'created' if created else 'present'} on the fake GitHub")


def seed_connection(api: Api, ws: str) -> str:
    body = {"name": CONNECTION, "available_in": "selected", "workspaces": [ws], "is_active": True,
            "bound_scopes": [REPOSITORY], "uses": {"agent_tools": {"level": "write"}},
            "access": {"github_url": f"{GIT_BASE}/api/v3", "github_owner": OWNER, "github_owner_type": "org",
                       "github_token": FAKE_TOKEN}}
    listing = api.call("GET", "/api/v1/admin/connections") or {}
    found = next((c for c in listing.get("connections", [])
                  if c.get("type") == "github" and c.get("name") == CONNECTION), None)
    if found is None:
        found = api.call("POST", "/api/v1/admin/connections", {**body, "type": "github"})
        print(f"connection: {CONNECTION} created")
    else:
        # The placeholder token is re-typed, so a moved port needs no separate secret rebind.
        answer = api.call("PUT", f"/api/v1/admin/connections/{found['id']}", body, ok=(200, 201, 409))
        if isinstance(answer, dict) and answer.get("detail") and "rebind" in json.dumps(answer):
            api.call("PUT", f"/api/v1/admin/connections/{found['id']}",
                     {**body, "access": {**body["access"], "confirm_secret_rebind": True}})
        print(f"connection: {CONNECTION} updated")
    result = api.call("POST", f"/api/v1/admin/connections/{found['id']}/test", {}, ok=()) or {}
    state = (result.get("state") or (result.get("result") or {}).get("state")) if isinstance(result, dict) else None
    print(f"connection: test {state or 'done'}")
    return str(found["id"])


def seed_repository(api: Api, ws: str, connection_id: str) -> None:
    """The Workspace's run repository through its connection (Work › Repositories › "Add a repository for runs")."""
    added = api.call("POST", f"/api/v1/workspaces/{ws}/repositories", {
        "connection_id": connection_id, "repository": REPOSITORY, "base_branch": "main",
        "test_command": TEST_COMMAND, "description": "Demo Shop sample app (fake GitHub)"}, ok=())
    if isinstance(added, dict) and added.get("id"):
        print(f"repository: {REPOSITORY} added for runs")
    elif isinstance(added, dict) and "repository_exists" in json.dumps(added):
        print(f"repository: {REPOSITORY} present")
    else:
        raise SystemExit(f"demo: the run repository was refused: {json.dumps(added)[:600]}")


def seed_review_bot(api: Api, ws: str) -> None:
    """The PR review bot on the demo repository: ``sync`` (no webhook), ``inform`` (never blocks a merge)."""
    listing = api.call("GET", f"/api/v1/workspaces/{ws}/pr-review-bot", ok=())
    rows = listing.get("repositories") if isinstance(listing, dict) else None
    row = next((item for item in rows or [] if item.get("repository") == f"github:{REPOSITORY}"), None)
    if row is None:
        print(f"review bot: {REPOSITORY} is not listed for the bot, skipped")
        return
    api.call("PUT", f"/api/v1/workspaces/{ws}/repositories/{row['id']}/pr-review-bot",
             {"trigger": "sync", "status_policy": "inform"})
    print(f"review bot: on for {REPOSITORY} (trigger sync, status inform)")


def seed_items(api: Api, ws: str) -> None:
    # The demo's own key prefix keeps its synthetic items recognizable: OCX-1, OCX-2.
    config = (api.call("GET", f"{PANEL}/projects/{ws}/config") or {}).get("config") or {}
    if config.get("platform_task_prefix") != KEY_PREFIX:
        api.call("PUT", f"{PANEL}/projects/{ws}/config", {"platform_task_prefix": KEY_PREFIX})
        print(f"workspace: work item keys {KEY_PREFIX}-…")
    listing = api.call("GET", f"/api/v1/secure-work/work-items?project_id={ws}&limit=200") or {}
    rows = listing.get("items", listing) if isinstance(listing, dict) else listing
    present = {str(row.get("title")) for row in rows or [] if isinstance(row, dict)}
    for item in ITEMS:
        if item["title"] in present:
            print(f"work item: {item['title']!r} present")
            continue
        created = api.call("POST", "/api/v1/secure-work/work-items", {"project_id": ws, **item})
        print(f"work item: {created.get('source_key')} {item['title']!r} created")


def _recorded_password(credentials: Path) -> str | None:
    text = credentials.read_text(encoding="utf-8") if credentials.exists() else ""
    if MEMBER_HEADING not in text:
        return None
    for line in text.split(MEMBER_HEADING, 1)[1].splitlines():
        if line.startswith("password: "):
            return line.split(": ", 1)[1].strip()
    return None


def seed_member(api: Api, ws: str, credentials: Path) -> None:
    password = _recorded_password(credentials)
    if password is None:
        password = secrets.token_urlsafe(18)
        credentials.parent.mkdir(parents=True, exist_ok=True)
        old = os.umask(0o077)
        try:
            with credentials.open("a", encoding="utf-8") as fh:
                fh.write(f"# Demo logins of this stack (local test values; git-ignored).\n"
                         f"## Admin\nusername: admin\n(its password is ADMIN_DEFAULT_PASSWORD in .env.local)\n\n"
                         f"{MEMBER_HEADING}\nusername: {MEMBER}\npassword: {password}\n")
        finally:
            os.umask(old)
    member = Api()
    try:
        member.login(MEMBER, password)
    except urllib.error.HTTPError:
        api.call("POST", "/api/v1/auth/register", {"username": MEMBER, "email": "demo.member@example.com",
                                                    "password": password, "display_name": "Demo Member"})
        member.login(MEMBER, password)
        print(f"member: {MEMBER} created (login in {credentials.name})")
    me = member.call("GET", "/api/v1/auth/me")
    access = api.call("GET", f"{PANEL}/projects/{ws}/access") or {}
    assignments = [{"user_id": a["user_id"], "project_roles": a.get("project_roles") or []}
                   for a in access.get("assignments", [])]
    if any(a["user_id"] == me["id"] for a in assignments):
        print(f"member: {MEMBER} in the Workspace")
        return
    api.call("PUT", f"{PANEL}/projects/{ws}/access", {
        "assignments": [*assignments, {"user_id": me["id"], "project_roles": ["member"]}],
        "group_assignments": [{"group_id": g["group_id"], "project_roles": g.get("project_roles") or []}
                              for g in access.get("group_assignments", [])],
        "role_assignments": [{"role_id": r["role_id"], "project_roles": r.get("project_roles") or []}
                             for r in access.get("role_assignments", [])]})
    print(f"member: {MEMBER} added to the Workspace (member, no admin role)")


async def _first_steps(api: Api) -> str:
    """The token, the Workspace, the repository and the Knowledge: one event loop for the platform's database pool."""
    api.token = await _admin_token()
    ws = seed_workspace(api)
    seed_git()
    await _knowledge(ws)
    return ws


def _bundle_tool():
    _backend()
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_bundle", BACKEND / "scripts" / "run_bundle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def seed_sample_run() -> None:
    """The recorded sample run, imported as a sample (``run_bundle.py``: demo only, once per Workspace)."""
    if not SAMPLE_RUN.exists():
        print(f"sample run: none recorded yet ({SAMPLE_RUN.parent.name}/{SAMPLE_RUN.name})")
        return
    await _bundle_tool().import_bundle(json.loads(SAMPLE_RUN.read_text(encoding="utf-8")), workspace=WORKSPACE,
                                    github=GIT_BASE, app_base=os.environ.get("OCTRYX_DEMO_APP_BASE", API_BASE))


async def _steps(api: Api) -> None:
    """Every step in one event loop (the platform's database pool belongs to one loop)."""
    ws = await _first_steps(api)
    connection_id = seed_connection(api, ws)
    seed_repository(api, ws, connection_id)
    seed_review_bot(api, ws)
    seed_items(api, ws)
    if os.environ.get("OCTRYX_DEMO_DIR"):
        seed_member(api, ws, Path(os.environ["OCTRYX_DEMO_DIR"]) / "CREDENTIALS.txt")
    await seed_sample_run()


def main() -> int:
    if not demo_switched_on():
        print("demo: off (only the demo's compose service sets OCTRYX_DEMO=1)")
        return 0
    refuse_production()
    api = Api()
    api.wait_healthy()
    asyncio.run(_steps(api))
    # The address a person opens: the platform's public origin (``OCTRYX_PORT``), not the API inside the pod.
    print(f"demo: ready in the Workspace {WORKSPACE!r} ({os.environ.get('OCTRYX_PUBLIC_ORIGIN') or API_BASE})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as exc:
        raise SystemExit(f"demo: not reachable: {exc.reason}") from None
