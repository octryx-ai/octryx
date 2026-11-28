"""Source Sync: ServiceNow knowledge articles and records, and the connector scheduler
(fake Table API over ``httpx.MockTransport``, no network)."""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import BuiltInToolConfig
from app.models.project.knowledge_evidence import KnowledgeSourceRevision, KnowledgeSourceRevisionOrigin
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector, KnowledgeSourceSyncRun
from app.runtime_toggles import knowledge_source_sync_scheduler_enabled
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ingestion.parser_port import ParserIdentity
from app.services.knowledge.ledger.errors import InvalidEvidenceRequestError
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.scheduler import KnowledgeSourceSyncScheduler
from app.services.knowledge.sources.sync.service import configure_connector
from app.services.knowledge.sources.sync.service_run import run_connector
from app.time_utils import utc_now
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace

# Connector targets pass the outbound URL policy (see tests/egress_support.py).
pytestmark = pytest.mark.usefixtures("public_source_dns")

SN = "https://acme.service-now.test"
KB = "0" * 31 + "a"
ARTICLE_SCOPE = f"kb_knowledge_baseIN{KB}^workflow_state=published^active=true"


def _sys_id(n: int) -> str:
    return f"{n:032x}"


class FakeServiceNow:
    def __init__(self) -> None:
        self.tables: dict[str, dict[str, dict]] = {"kb_knowledge": {}, "incident": {}}
        self.queries: list[str] = []

    def article(self, n: int, title: str, html: str, *, can_read: str | None = "", mod: int = 1) -> str:
        record = {"number": f"KB00{n}", "short_description": title, "text": html, "article_type": "html"}
        record.update(sys_mod_count=str(mod), sys_updated_on="2026-09-01 10:00:00", roles="")
        if can_read is not None:
            record.update(can_read_user_criteria=can_read, cannot_read_user_criteria="")
        self.tables["kb_knowledge"][_sys_id(n)] = record
        return _sys_id(n)

    def incident(self, n: int, title: str, text: str, *, domain: str = "global") -> str:
        record = {"number": f"INC00{n}", "short_description": title, "description": text, "state": "Resolved"}
        record.update(sys_mod_count="3", sys_updated_on="2026-09-02 10:00:00", sys_domain=domain)
        record.update(close_notes="Restarted the gateway.", work_notes="internal: never rendered")
        self.tables["incident"][_sys_id(n)] = record
        return _sys_id(n)

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.headers["Authorization"] == "Bearer sn-token"
        parts = request.url.path.removeprefix("/api/now/table/").split("/")
        query = parse_qs(urlsplit(str(request.url)).query)
        table = self.tables[parts[0]]
        if len(parts) == 2:
            return httpx.Response(200, json={"result": {"sys_id": parts[1], **table[parts[1]]}})
        self.queries.append(query["sysparm_query"][0])
        fields = query["sysparm_fields"][0].split(",")
        offset, limit = int(query["sysparm_offset"][0]), int(query["sysparm_limit"][0])
        rows = [
            {key: value for key, value in {"sys_id": sys_id, **record}.items() if key in fields}
            for sys_id, record in sorted(table.items())
        ]
        return httpx.Response(200, json={"result": rows[offset : offset + limit]})


class StubParser:
    identity = ParserIdentity(name="docling-serve", version="1.35.0+p1", sandbox="no_network_uds")


async def _setup(db, *, schedule: bool = False, allowed=("kb_knowledge", "incident"), **scope):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    tool = {"servicenow_url": SN, "servicenow_auth_mode": "bearer_token", "servicenow_token": "sn-token", "servicenow_allowed_tables": list(allowed)}
    db.add(BuiltInToolConfig(tool_name="servicenow", project_id=workspace_id, config=tool, is_active=True))
    await db.flush()
    runtime, _, evidence_index = build_runtime()
    runtime = dataclasses.replace(runtime, parser=StubParser())
    scope = scope or {"knowledge_bases": [KB], "tables": ["incident"]}
    config = validate_config(
        connector_key="snow", kind="servicenow", schedule_enabled=schedule, schedule_interval_minutes=15, **scope
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


async def _count(db, model, **where) -> int:
    statement = select(func.count()).select_from(model)
    for key, value in where.items():
        statement = statement.where(getattr(model, key) == value)
    return (await db.execute(statement)).scalar_one()


def _counts(run) -> dict:
    return {key: run.report[key] for key in ("created", "updated", "unchanged", "retired", "skipped", "failed")}


async def test_a_first_sync_creates_linked_revisions_and_an_unchanged_rerun_creates_none(db) -> None:
    setup = await _setup(db)
    snow = FakeServiceNow()
    article = snow.article(1, "Reset the VPN", "<h2>Steps</h2><p>Open the portal.</p>")
    incident = snow.incident(2, "Gateway down", "The payment gateway answered 502.")

    first = await _run(db, setup, snow)

    assert first.state == "completed" and _counts(first)["created"] == 2
    origins = (await db.execute(select(KnowledgeSourceRevisionOrigin.source_url))).scalars().all()
    assert sorted(origins) == [f"{SN}/incident.do?sys_id={incident}", f"{SN}/kb_view.do?sys_kb_id={article}"]

    second = await _run(db, setup, snow)

    assert _counts(second) == {"created": 0, "updated": 0, "unchanged": 2, "retired": 0, "skipped": 0, "failed": 0}
    assert await _count(db, KnowledgeSourceRevision, project_id=setup[0].project_id) == 2


async def test_restricted_items_are_withheld_and_an_undeterminable_acl_is_a_failure(db) -> None:
    setup = await _setup(db)
    snow = FakeServiceNow()
    snow.article(1, "Public how-to", "<p>Everyone may read this.</p>")
    restricted = snow.article(2, "HR salaries", "<p>Confidential.</p>", can_read=_sys_id(99))
    unknown = snow.article(3, "No criteria fields", "<p>Unknown audience.</p>", can_read=None)
    domain = snow.incident(4, "Tenant B outage", "Separated domain.", domain=_sys_id(77))

    run = await _run(db, setup, snow)

    assert _counts(run)["created"] == 1 and _counts(run)["skipped"] == 2 and _counts(run)["failed"] == 1
    by_id = {o["external_id"]: o for o in run.outcomes}
    assert by_id[restricted] == {
        "external_id": restricted,
        "title": None,
        "outcome": "skipped",
        "reason": "restricted_acl",
    }
    assert by_id[domain]["reason"] == "restricted_acl" and by_id[domain]["title"] is None
    assert by_id[unknown]["outcome"] == "failed" and by_id[unknown]["reason"] == "acl_unresolved"
    # Neither the restricted nor the unknown bytes reached the ledger.
    assert await _count(db, KnowledgeSourceRevision, project_id=setup[0].project_id) == 1


async def test_an_encoded_query_can_only_narrow_the_configured_scope(db) -> None:
    for widening in (
        "ORkb_knowledge_base!=x",  # a leading OR would bind to the last scope condition
        "short_descriptionLIKEvpn^NQactive=false",  # a new query is OR-ed with the scope
        "priority=1^EQ",  # EQ ends the query early
        "priority=1^ORDERBYnumber",  # the connector owns the order
        "sys_created_on>javascript:gs.daysAgo(3)",  # evaluated on the instance
        "priority=1^^x=1",
    ):
        with pytest.raises(InvalidEvidenceRequestError):
            validate_config(connector_key="snow", kind="servicenow", knowledge_bases=[KB], article_query=widening)
    with pytest.raises(InvalidEvidenceRequestError):
        validate_config(connector_key="snow", kind="servicenow", tables=["sys_user"])

    setup = await _setup(db, knowledge_bases=[KB], article_query="short_descriptionLIKEvpn^ORtextLIKEvpn")
    snow = FakeServiceNow()
    snow.article(1, "Reset the VPN", "<p>Open the portal.</p>")
    await _run(db, setup, snow)

    assert snow.queries == [
        f"{ARTICLE_SCOPE}^short_descriptionLIKEvpn^ORtextLIKEvpn^ORDERBYsys_created_on^ORDERBYsys_id"
    ]

    # A scope outside the tool's own table allowlist is refused before anything is read.
    with pytest.raises(Exception) as refused:
        await _setup(db, allowed=("incident",))
    assert getattr(refused.value, "reason", None) == "scope_not_allowed"


def _factory(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)


def _scheduler(db, runtime, snow) -> KnowledgeSourceSyncScheduler:
    return KnowledgeSourceSyncScheduler(
        _factory(db), runtime_provider=lambda: runtime, transport=httpx.MockTransport(snow.handler)
    )


async def test_the_scheduler_is_off_by_default_and_ignores_unscheduled_connectors(db) -> None:
    assert knowledge_source_sync_scheduler_enabled(env={}) is False
    setup = await _setup(db, schedule=False)
    snow = FakeServiceNow()
    snow.incident(1, "Gateway down", "Answered 502.")

    outcomes = await _scheduler(db, setup[2], snow).run_tick()

    assert outcomes == {} and await _count(db, KnowledgeSourceSyncRun, connector_id=setup[3].id) == 0


async def test_an_enabled_schedule_runs_a_due_connector_once_and_respects_the_lease(db) -> None:
    setup = await _setup(db, schedule=True, tables=["incident"])
    runtime, row_id = setup[2], setup[3].id
    snow = FakeServiceNow()
    snow.incident(1, "Gateway down", "Answered 502.")
    scheduler = _scheduler(db, runtime, snow)

    first = await scheduler.run_tick()
    again = await scheduler.run_tick()

    assert first == {"completed": 1} and again == {}
    assert await _count(db, KnowledgeSourceSyncRun, connector_id=row_id) == 1
    row = await db.get(KnowledgeSourceConnector, row_id)
    await db.refresh(row)
    assert row.next_scheduled_at > utc_now() + timedelta(minutes=14)

    # Due again while another run holds the lease: the slot is spent, no second run overlaps.
    row.next_scheduled_at = utc_now() - timedelta(minutes=1)
    row.run_lease_until = utc_now() + timedelta(minutes=10)
    await db.commit()

    assert await scheduler.run_tick() == {"run_in_progress": 1}
    assert await _count(db, KnowledgeSourceSyncRun, connector_id=row_id) == 1
