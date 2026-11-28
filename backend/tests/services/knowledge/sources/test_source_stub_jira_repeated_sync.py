"""Regression: the first Jira sync item's ``('failed', 'unavailable')`` outcome is not an egress refusal."""

from __future__ import annotations

import asyncio
import json
import logging

from app.models import BuiltInToolConfig
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.contract import REASON_EGRESS_REFUSED, REASON_SOURCE_UNAVAILABLE
from app.services.knowledge.sources.sync.service import configure_connector
from app.services.knowledge.sources.sync.service_run import run_connector
from tests import source_stub_support as stubs
from tests.egress_support import stub_settings, use_stub_settings
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.support.knowledge_evidence_s3_support import FakeS3Client

fx = stubs.jira_fixtures
stub = stubs.jira_stub
FIRST_ITEM = fx.ISSUES[0]["id"]
RUNS = 3


async def _serve_stub(requests: list[str]) -> asyncio.base_events.Server:
    async def _answer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1")
        method, target, _ = head.split("\r\n", 1)[0].split(" ", 2)
        authorization = next(
            (line.split(":", 1)[1].strip() for line in head.split("\r\n") if line.lower().startswith("authorization:")),
            None,
        )
        requests.append(f"{method} {target.split('?', 1)[0]}")
        status, payload = stub.handle(method, target, authorization)
        body = json.dumps(payload).encode()
        writer.write(
            f"HTTP/1.0 {status} X\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        writer.close()

    return await asyncio.start_server(_answer, "127.0.0.1", 0)


async def _jira_workspace(db, base_url: str, run: int):
    workspace_id = await seed_workspace(db)
    owner_id = await seed_member(db, workspace_id=workspace_id, role="owner", username=f"jira-repeat-{run}")
    owner = await authorize_workspace(db, current_user=await fetch_user(db, owner_id), workspace_id=workspace_id)
    tool = {
        "jira_auth_mode": "cloud_api_token",
        "jira_url": base_url,
        "jira_email": fx.STUB_USERNAME,
        "jira_token": fx.STUB_TOKEN,
        "jira_allowed_projects": [fx.PROJECT_KEY],
    }
    db.add(BuiltInToolConfig(tool_name="jira", project_id=workspace_id, config=tool, is_active=True))
    await db.flush()
    config = validate_config(
        connector_key="ops-releases", kind="jira", project_keys=[fx.PROJECT_KEY], releases=fx.RELEASES
    )
    row = await configure_connector(db, authorized=owner, config=config, actor_id=owner_id)
    return owner, owner_id, row


def _outcomes(run) -> dict[str, tuple[str, str | None]]:
    return {o["external_id"]: (o["outcome"], o["reason"]) for o in run.outcomes}


async def test_consecutive_jira_syncs_over_a_loopback_socket_create_the_first_item_every_time(db, monkeypatch):
    requests: list[str] = []
    server = await _serve_stub(requests)
    port = server.sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    use_stub_settings(monkeypatch, stub_settings(hosts=f"127.0.0.1:{port}"))
    runtime, _, evidence_index = build_runtime()
    try:
        for attempt in range(RUNS):
            owner, owner_id, row = await _jira_workspace(db, base_url, attempt)
            # No transport: the real pinned egress pool connects to the stub's socket.
            run = await run_connector(db, runtime=runtime, authorized=owner, row=row, actor_id=owner_id)
            assert run.state == "completed", (attempt, run.state, run.reason)
            assert _outcomes(run) == fx.SYNC_OUTCOMES, attempt
            assert _outcomes(run)[FIRST_ITEM] == ("created", None)
    finally:
        server.close()
        await server.wait_closed()
    assert requests and all(line.startswith("GET ") for line in requests)


class _FirstWriteFails(FakeS3Client):
    def put_object(self, **kwargs: object) -> dict[str, object]:
        self.unavailable = "PutObject" not in self.calls
        try:
            return super().put_object(**kwargs)
        finally:
            self.unavailable = False


async def test_one_object_store_write_failure_is_exactly_the_live_first_item_signature(db, monkeypatch, caplog):
    owner, owner_id, row = await _jira_workspace(db, f"http://{fx.STUB_HOST}:{fx.STUB_PORT}", 0)
    runtime, _, evidence_index = build_runtime(s3=_FirstWriteFails())
    use_stub_settings(monkeypatch, stub_settings())

    transport = stubs.transport(stub, f"http://{fx.STUB_HOST}:{fx.STUB_PORT}")
    caplog.set_level(logging.WARNING, logger="app.services.knowledge.objects.store")
    run = await run_connector(db, runtime=runtime, authorized=owner, row=row, actor_id=owner_id, transport=transport)

    expected = dict(fx.SYNC_OUTCOMES)
    expected[FIRST_ITEM] = ("failed", "unavailable")
    assert run.state == "completed"
    assert _outcomes(run) == expected
    assert "unavailable" not in {REASON_EGRESS_REFUSED, REASON_SOURCE_UNAVAILABLE}
    failures = [r.getMessage() for r in caplog.records if "Knowledge object write failed" in r.getMessage()]
    assert len(failures) == 1 and "state=unavailable cause=InternalError seconds=" in failures[0]
    assert owner.project_id not in failures[0]
