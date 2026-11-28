"""A bitbucket.org repository syncs into Knowledge with its Cloud connection, and the poll reads green CI then the merge on Bitbucket Cloud."""

from __future__ import annotations

import base64
import io
import ipaddress
import tarfile

import httpx
import pytest
from sqlalchemy import select

from app.models import WorkflowRun
from app.models.project.knowledge_evidence import KnowledgeSourceRevisionOrigin
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.contract import ConnectorError
from app.services.knowledge.sources.sync.service import configure_connector
from app.services.knowledge.sources.sync.service_run import run_connector
from app.services.secure_work.pull_requests.record_identity import pull_request_identity
from app.services.workflow_runs import watch
from tests.bitbucket_cloud_workflow_support import EMAIL, HEAD, TOKEN, _cloud_workspace
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


def _tarball(sha: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        top = tarfile.TarInfo(f"acme-payments-{sha[:12]}")
        top.type = tarfile.DIRTYPE
        tar.addfile(top)
        data = b"def total(a, b):\n    return a + b\n"
        info = tarfile.TarInfo(f"acme-payments-{sha[:12]}/calc.py")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


@pytest.fixture
def dns(monkeypatch):
    async def _resolve(hostname: str, port: int | None):
        return {ipaddress.ip_address("203.0.113.10")}

    async def _no_allowlist(connection: str) -> frozenset[str]:
        return frozenset()

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _resolve)
    monkeypatch.setattr("app.services.outbound_egress.target_check._private_host_keys", _no_allowlist)


PIPELINE = "/2.0/repositories/acme/payments/pipelines/6"


class LiveShapedCloud:
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.pr_state = "OPEN"

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.paths.append(path)
        if path == f"/2.0/repositories/acme/payments/commit/{HEAD}/statuses":
            return httpx.Response(200, json={"values": [{
                "type": "build", "key": "{pipeline-uuid}", "state": "SUCCESSFUL", "name": "Pipeline #6 for feature",
                "url": "https://bitbucket.org/acme/payments/pipelines/results/6", "commit": {"hash": HEAD}}]})
        if path == f"{PIPELINE}/steps/":
            return httpx.Response(200, json={"values": [{"uuid": "{step-test}"}, {"uuid": "{step-lint}"}]})
        if path == f"{PIPELINE}/steps/{{step-test}}/test_reports/test_cases":
            return httpx.Response(200, json={"values": [{"name": "test_total", "status": "SUCCESSFUL",
                                                         "fully_qualified_name": "tests.test_calc.test_total"}]})
        if path == "/2.0/repositories/acme/payments/pullrequests/1":
            return httpx.Response(200, json={
                "id": 1, "title": "PAY-1: Totals", "state": self.pr_state, "participants": [],
                "source": {"branch": {"name": "feature/PAY-1-totals"}}, "destination": {"branch": {"name": "main"}},
                "links": {"html": {"href": "https://bitbucket.org/acme/payments/pull-requests/1"}}})
        return httpx.Response(404, json={"type": "error", "error": {"message": "Not found"}})


async def test_a_bitbucket_cloud_repository_is_synced_with_its_connection(db, dns) -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("authorization", "")))
        if request.url.path == "/2.0/repositories/acme/payments/commit/main":
            return httpx.Response(200, json={"type": "commit", "hash": HEAD})
        if request.url.path == f"/acme/payments/get/{HEAD}.tar.gz":
            return httpx.Response(200, content=_tarball(HEAD))
        return httpx.Response(404)

    async def configure(bound: str):
        workspace_id = await _cloud_workspace(db, bound=bound)
        user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
        authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
        config = validate_config(connector_key="payments", kind="git_repository", fetch_mode="remote_git",
                                 repository_url="https://bitbucket.org/acme/payments", ref="main")
        return authorized, user_id, await configure_connector(db, authorized=authorized, config=config, actor_id=user_id)

    with pytest.raises(ConnectorError) as refused:  # no connection of this Workspace binds the repository
        await configure("acme/other")
    assert refused.value.reason == "connection_not_configured_for_scope" and not seen
    authorized, user_id, row = await configure("acme/payments")
    runtime, _, evidence_index = build_runtime()
    row = await db.get(KnowledgeSourceConnector, row.id)
    run = await run_connector(db, runtime=runtime, authorized=authorized, row=row, actor_id=user_id,
                              transport=httpx.MockTransport(handler))
    assert run.state == "completed" and run.report["created"] == 1, run.reason
    origins = (await db.execute(select(KnowledgeSourceRevisionOrigin.source_url))).scalars().all()
    assert f"https://bitbucket.org/acme/payments/src/{HEAD}/calc.py" in origins
    expected_auth = "Basic " + base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
    assert seen == [("https://api.bitbucket.org/2.0/repositories/acme/payments/commit/main", expected_auth),
                    (f"https://bitbucket.org/acme/payments/get/{HEAD}.tar.gz", expected_auth)]


async def test_the_poll_reads_ci_green_then_the_merge_on_bitbucket_cloud(db, monkeypatch) -> None:
    from app.tools.bitbucket_impl import _bitbucket_cloud
    from tests.test_workflow_run_platform_actions import _run as start

    cloud = LiveShapedCloud()
    monkeypatch.setattr(_bitbucket_cloud, "_transport", lambda: httpx.MockTransport(cloud.handler))
    workspace_id = await _cloud_workspace(db)
    definition = {"execution_kind": "phased", "nodes": [
        {"id": "start", "type": "start"},
        {"id": "ci", "type": "watch", "label": "CI", "config": {"conditions": ["ci.succeeded", "ci.failed"],
                                                                 "advance": "auto"}},
        {"id": "merged", "type": "watch", "label": "Merged", "config": {"conditions": ["pr.merged"],
                                                                         "advance": "auto"}},
        {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
        {"id": "blocked", "type": "outcome", "config": {"outcome": "blocked"}}], "edges": [
        {"id": "s", "source_node_id": "start", "target_node_id": "ci"},
        {"id": "c1", "source_node_id": "ci", "target_node_id": "merged", "when": "ci.succeeded"},
        {"id": "c2", "source_node_id": "ci", "target_node_id": "blocked", "when": "ci.failed"},
        {"id": "m1", "source_node_id": "merged", "target_node_id": "done", "when": "pr.merged"}]}
    run = await start(db, definition, project_id=workspace_id, repository="bitbucket:acme/payments")
    run.branch, run.context = "feature/PAY-1-totals", {**dict(run.context or {}), "head_sha": HEAD}
    url = "https://bitbucket.org/acme/payments/pull-requests/1"
    run.pull_request = {"provider": "bitbucket", "repository": "acme/payments", "id": "1", "url": url,
                        "identity": pull_request_identity("bitbucket", url, "acme/payments", "1")}
    await db.commit()
    assert (run.current_node_id, run.waiting_kind) == ("ci", "watching")

    assert await watch.poll_watching_runs(db) == 1
    run = await db.get(WorkflowRun, run.id)
    assert run.context["ci"]["state"] == "succeeded", run.context["ci"]
    assert (run.context["ci"]["reason"], run.context["ci"]["sha"]) == ("", HEAD)
    ci_run = run.context["tests"]["runs"][-1]  # the test step's report is recorded (no working copy: unkeyed here)
    assert (ci_run["source"], ci_run["sha"]) == ("ci", HEAD) and "test_total" in str(ci_run.get("unresolved"))
    assert f"{PIPELINE}/steps/{{step-lint}}/test_reports/test_cases" in cloud.paths
    assert run.current_node_id == "merged"

    assert await watch.poll_watching_runs(db) == 0
    cloud.pr_state = "MERGED"
    assert await watch.poll_watching_runs(db) == 1
    run = await db.get(WorkflowRun, run.id)
    assert (run.status, run.outcome) == ("completed", "done")
