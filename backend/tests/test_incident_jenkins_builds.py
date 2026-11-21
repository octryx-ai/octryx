"""``list_jenkins_builds`` — the alert target's Jenkins builds in the alert window, bounded and read-only.

- ``job`` must be one of the target's ``ci.jenkins_jobs`` (without a scope: only the Workspace's deploy job);
- builds are filtered to the window (default: the alert window), at most ``limit`` ≤ 20, newest first, with the
  test summary on request;
- no Jenkins connection, an unreachable or failing Jenkins → ``unavailable`` (transport stub, no network);
- it only reads: every request the real client sends is a GET.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

import app.tools.jenkins_builds as jenkins_module
from app.services.secure_work.cicd.jenkins_client import JenkinsClient, JenkinsRuntimeConfig
from app.services.workflow_runs import records
from app.services.workflow_runs.platform import deploy
from app.tools.alert_scope import AlertScope
from app.tools.context import ToolContext
from app.tools.jenkins_builds import ListJenkinsBuilds

NOW = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)
SCOPE = AlertScope(target_id="checkout", jenkins_jobs=("deploy-checkout",),
                   window_start=datetime(2026, 10, 15, 9, 0, tzinfo=UTC), window_end=None)


def _ms(hour: int, minute: int = 0) -> int:
    return int(datetime(2026, 10, 15, hour, minute, tzinfo=UTC).timestamp() * 1000)


BUILDS = [  # Jenkins lists newest first
    {"number": 44, "url": "https://ci.example.test/job/deploy-checkout/44/", "result": None, "building": True,
     "timestamp": _ms(9, 50), "duration": 0, "actions": [{"lastBuiltRevision": {"SHA1": "c0ffee"}}]},
    {"number": 43, "url": "https://ci.example.test/job/deploy-checkout/43/", "result": "FAILURE", "building": False,
     "timestamp": _ms(9, 20), "duration": 60000, "actions": [{"lastBuiltRevision": {"SHA1": "bad1"}}]},
    {"number": 42, "url": "https://ci.example.test/job/deploy-checkout/42/", "result": "SUCCESS", "building": False,
     "timestamp": _ms(7, 0), "duration": 50000, "actions": []},
]


@pytest.fixture
def jenkins(monkeypatch):
    requests: list[httpx.Request] = []
    state = {"connected": True, "fail": None}
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if state["fail"]:
            raise state["fail"]
        if request.url.path.endswith("/testReport/api/json"):
            number = request.url.path.split("/")[-4]
            if number == "44":
                return httpx.Response(404)
            return httpx.Response(200, json={"failCount": 2, "skipCount": 1, "totalCount": 30, "suites": [{}]})
        return httpx.Response(200, json={"builds": BUILDS})

    def factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    async def jenkins_client(_db, _run):
        if not state["connected"]:
            return None
        return JenkinsClient(JenkinsRuntimeConfig(base_url="https://ci.example.test", username="bot",
                                                  token="fake-token"), client_factory=factory)

    async def deploy_job(_db, _run):
        return "deploy-checkout"

    async def no_run(_db, _session_id):
        return None

    monkeypatch.setattr(deploy, "jenkins_client", jenkins_client)
    monkeypatch.setattr(deploy, "deploy_job", deploy_job)
    monkeypatch.setattr(records, "active_run_for_session", no_run)
    monkeypatch.setattr(jenkins_module, "utc_now_aware", lambda: NOW)

    def scoped(scope):
        async def run_alert_scope(_context):
            return scope
        monkeypatch.setattr(jenkins_module, "run_alert_scope", run_alert_scope)

    scoped(SCOPE)
    return requests, state, scoped


def _context() -> ToolContext:
    return ToolContext(user_id="u", project_ids=["p"], roles=["admin"], session_id="s", project_config={},
                       db=object())


async def _list(**params) -> dict:
    return await ListJenkinsBuilds().execute(params, _context())


@pytest.mark.asyncio
async def test_a_job_outside_the_scope_is_refused_before_any_request(jenkins):
    requests, _state, scoped = jenkins
    refused = await _list(job="deploy-payments")
    assert (refused["error"], refused["evidence"]["status"], refused["allowed_jobs"]) == (
        "job_out_of_scope", "refused", ["deploy-checkout"])
    scoped(None)  # without a scope: the Workspace's deploy job only
    assert (await _list(job="release-everything"))["error"] == "job_out_of_scope"
    assert requests == []
    assert (await _list())["job"] == "deploy-checkout"  # the only allowed job is the default


@pytest.mark.asyncio
async def test_builds_are_filtered_by_the_alert_window_and_bounded(jenkins):
    requests, _state, _scoped = jenkins
    result = await _list(job="deploy-checkout", include_tests=True)
    assert [build["number"] for build in result["builds"]] == ["44", "43"]  # 42 ran before the window
    assert (result["start"], result["end"]) == ("2026-10-15T09:00:00Z", "2026-10-15T10:00:00Z")
    assert result["builds"][1] | {"tests": None} == {
        "number": "43", "status": "failed", "result": "FAILURE", "building": False,
        "timestamp": "2026-10-15T09:20:00Z", "duration_ms": 60000, "commit": "bad1",
        "url": "https://ci.example.test/job/deploy-checkout/43/", "tests": None}
    assert result["builds"][1]["tests"] == {"available": True, "total": 30, "failed": 2, "skipped": 1}
    assert result["builds"][0]["tests"]["available"] is False  # still building: no report
    assert (result["evidence"]["status"], result["evidence"]["count"], result["evidence"]["target_id"]) == (
        "ok", 2, "checkout")
    limited = await _list(job="deploy-checkout", limit=1)
    assert [build["number"] for build in limited["builds"]] == ["44"]
    assert (await _list(job="deploy-checkout", limit=500))["limit"] == 20
    # Only reads: the real client sent GETs, never a trigger, re-run or stop.
    assert requests and {request.method for request in requests} == {"GET"}
    assert not any(part in request.url.path for request in requests for part in ("/build", "/stop"))


@pytest.mark.asyncio
async def test_a_window_without_builds_is_a_targeted_empty(jenkins):
    _requests, _state, _scoped = jenkins
    result = await _list(job="deploy-checkout", since="2026-10-15T09:55:00Z")
    assert (result["builds"], result["evidence"]["status"], result["evidence"]["target_id"]) == (
        [], "empty", "checkout")
    before = await _list(job="deploy-checkout", since="2026-10-14T00:00:00Z", until="2026-10-14T06:00:00Z")
    assert (before["error"], before["evidence"]["status"]) == ("window_out_of_scope", "refused")


@pytest.mark.asyncio
async def test_no_connection_or_a_failing_jenkins_is_unavailable(jenkins):
    _requests, state, _scoped = jenkins
    state["connected"] = False
    missing = await _list(job="deploy-checkout")
    assert (missing["error"], missing["evidence"]["status"]) == ("jenkins_not_configured", "unavailable")
    state["connected"], state["fail"] = True, httpx.ConnectError("refused")
    failing = await _list(job="deploy-checkout")
    assert (failing["code"], failing["evidence"]["status"]) == ("jenkins_unavailable", "unavailable")
    assert "builds" not in failing
