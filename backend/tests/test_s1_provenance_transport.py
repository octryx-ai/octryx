"""S1 exact-version representation and serving-connection dispatch pins, with bounded transports."""
from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest

from app.services.knowledge.sources.sync.confluence import ConfluenceConnector
from app.services.knowledge.sources.sync.confluence_pinned import PinnedViewRefusedError
from app.services.knowledge.sources.sync.connections import SourceConnection
from app.services.knowledge.sources.sync.scope_connections import ScopeConnections
from app.services.workflow_runs.documentation import knowledge
from app.services.workflow_runs.documentation.knowledge_proof import (
    REASON_SOURCE_CONNECTION,
    publication_pin,
)
from tests.egress_support import public_source_dns  # noqa: F401 - the fixture, used by name

pytestmark = pytest.mark.asyncio
BASE = "https://fixture.atlassian.net/wiki"


def payload(version=4):
    return {"id": "42", "type": "page", "status": "current", "title": "Feature",
            "version": {"number": version}, "body": {"view": {"representation": "view", "value": "<p>Hello</p>"}},
            "_links": {"base": BASE, "webui": "/spaces/DOCS/pages/42"}}


def source():
    return SourceConnection(kind="confluence", base_url=BASE, principal="fixture", secret="fake-transport-secret")


@pytest.mark.usefixtures("public_source_dns")  # the egress policy resolves the host: never real DNS
async def test_pinned_view_binds_observed_version_and_representation_digests():
    requests = []

    def answer(request):
        requests.append(request)
        return httpx.Response(200, json=payload())

    connector = ConfluenceConnector(source(), spaces=("DOCS",), transport=httpx.MockTransport(answer))
    view = await connector.fetch_pinned_view("42", version=4)
    assert view.version == 4 and view.read_base == BASE
    assert view.view_raw_digest != view.document_digest
    assert view.document_digest == "sha256:" + view.document_sha256
    assert len(requests) == 1 and requests[0].url.path == "/wiki/rest/api/content/42"
    assert requests[0].url.params["expand"] == "body.view,version"


@pytest.mark.parametrize("shape", [payload(5), {}, {**payload(), "version": {"number": True}},
                                   {**payload(), "body": {"view": {"value": "<p>Hello</p>"}}}])
async def test_moved_version_or_malformed_view_never_proves_publication(shape):
    connector = ConfluenceConnector(source(), spaces=("DOCS",), transport=httpx.MockTransport(
        lambda _request: httpx.Response(200, json=shape)))
    with pytest.raises(PinnedViewRefusedError):
        await connector.fetch_pinned_view("42", version=4)


async def test_sync_dispatch_rejects_same_endpoint_serving_identity_change(db, monkeypatch):
    from app.services.knowledge.sources.sync import service_run
    from tests.knowledge_evidence_runtime_support import build_runtime
    from tests.s1_receipt_flow_support import bind_publication

    runtime, _s3, evidence_index = build_runtime()
    bound = await bind_publication(db, runtime, evidence_index)
    page = {"space_key": "DOCS", "instance": BASE, "connection_id": "approved"}
    scoped = ScopeConnections({"different": source()}, {"DOCS": "different"})
    dispatched = []

    @asynccontextmanager
    async def same_session():
        yield db

    async def run_connector(*_args, **kwargs):
        refused = kwargs["pin"](scoped)
        assert refused == REASON_SOURCE_CONNECTION
        # The source runner checks its pin before creating a reader or fetching anything.
        return SimpleNamespace(reason=refused, state="needs_configuration")

    monkeypatch.setattr(knowledge, "source_sync_session", same_session)
    monkeypatch.setattr(knowledge, "evidence_runtime", lambda: runtime)
    monkeypatch.setattr(service_run, "run_connector", run_connector)
    assert await knowledge._run_source(db, bound.run, bound.connector, page=page) == REASON_SOURCE_CONNECTION
    assert not dispatched
    assert publication_pin(page)(ScopeConnections({"approved": source()}, {"DOCS": "approved"})) == ""
