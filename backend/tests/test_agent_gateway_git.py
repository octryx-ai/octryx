"""The run-bound git gateway: a session's token serves its own run's branch and nothing else, read-only, and ends
with the run."""

from __future__ import annotations

import base64
import subprocess
import uuid
from datetime import timedelta
from pathlib import Path

import jwt
import pytest

from app.models import WorkflowRun
from tests.device_job_session_parity_support import GATEWAY
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_acceptance_support import systems  # noqa: F401 - the stubbed Jira and GitHub fixture
from tests.workspace_preparation_support import _device_at_tests_first, _server_pipeline  # noqa: F401

pytestmark = pytest.mark.usefixtures("scripted_pool")

GIT = "/api/v1/agent-gateway/git"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.email=t@stub.test", "-c", "user.name=t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def _pkt(line: str) -> bytes:
    return f"{len(line) + 4:04x}".encode() + line.encode()


def _want(sha: str) -> bytes:
    return _pkt(f"want {sha}\n") + b"0000" + _pkt("done\n")


async def _run_with_a_hidden_branch(client, auth_headers, db, systems):  # noqa: F811
    run_id, working_copy, _gateway, _policy, headers = await _device_at_tests_first(client, auth_headers, db, systems)
    run = await db.get(WorkflowRun, run_id)
    _git(working_copy, "checkout", "-q", "-B", "someone-elses-work")
    (working_copy / "secret.txt").write_text("not this run's\n")
    _git(working_copy, "add", "secret.txt")
    _git(working_copy, "commit", "-q", "-m", "another branch")
    hidden = _git(working_copy, "rev-parse", "HEAD")
    _git(working_copy, "checkout", "-q", "-B", run.branch, "HEAD~1")
    (working_copy / "story.py").write_text("# the run's branch\n")
    _git(working_copy, "add", "story.py")
    _git(working_copy, "commit", "-q", "-m", "the run's commit")
    return run, headers, _git(working_copy, "rev-parse", "HEAD"), hidden


async def _token(client, headers) -> dict:
    answer = await client.post(f"{GATEWAY}/git-token", headers=headers)
    assert answer.status_code == 200, answer.text
    return answer.json()


@pytest.mark.asyncio
async def test_a_session_reads_only_its_runs_branch_and_never_pushes(client, auth_headers, db, systems):  # noqa: F811
    run, headers, head, hidden = await _run_with_a_hidden_branch(client, auth_headers, db, systems)
    body = await _token(client, headers)
    assert (body["state"], body["path"], body["branch"]) == ("ready", f"{GIT}/{run.id}", run.branch)
    assert 0 < body["expires_in"] <= 600
    basic = {"Authorization": "Basic " + base64.b64encode(f"octryx-run:{body['token']}".encode()).decode()}

    refs = await client.get(f"{body['path']}/info/refs?service=git-upload-pack", headers=basic)
    assert refs.status_code == 200, refs.text
    assert refs.headers["content-type"] == "application/x-git-upload-pack-advertisement"
    advertised = refs.content.decode(errors="replace")
    assert f"{head} refs/heads/{run.branch}" in advertised
    assert "someone-elses-work" not in advertised and hidden not in advertised

    pack = await client.post(f"{body['path']}/git-upload-pack", headers=basic, content=_want(head))
    assert pack.status_code == 200 and b"PACK" in pack.content
    other = await client.post(f"{body['path']}/git-upload-pack", headers=basic, content=_want(hidden))
    # A hidden branch's commit cannot be asked for by its name either.
    assert b"PACK" not in other.content and b"not our ref" in other.content

    for push in (client.get(f"{body['path']}/info/refs?service=git-receive-pack", headers=basic),
                 client.post(f"{body['path']}/git-receive-pack", headers=basic, content=b"0000")):
        refused = await push
        assert (refused.status_code, refused.json()["reason"]) == (403, "git_push_through_platform")


@pytest.mark.asyncio
async def test_the_token_opens_its_own_run_only_and_ends_with_it(client, auth_headers, db, systems):  # noqa: F811
    from app.config import get_settings

    run, headers, _head, _hidden = await _run_with_a_hidden_branch(client, auth_headers, db, systems)
    token = (await _token(client, headers))["token"]
    bearer = {"Authorization": f"Bearer {token}"}

    unauthenticated = await client.get(f"{GIT}/{run.id}/info/refs?service=git-upload-pack")
    assert unauthenticated.status_code == 401 and unauthenticated.headers["www-authenticate"].startswith("Basic")
    other_run = await client.get(f"{GIT}/{uuid.uuid4()}/info/refs?service=git-upload-pack", headers=bearer)
    assert (other_run.status_code, other_run.json()["reason"]) == (403, "git_token_other_run")

    claims = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"], audience="octryx-git")
    claims["exp"] = claims["exp"] - timedelta(hours=1).total_seconds()
    expired = jwt.encode(claims, get_settings().jwt_secret, algorithm="HS256")
    late = await client.get(f"{GIT}/{run.id}/info/refs?service=git-upload-pack",
                            headers={"Authorization": f"Bearer {expired}"})
    assert (late.status_code, late.json()["reason"]) == (401, "git_token_invalid")
    gateway_token = headers["Authorization"].removeprefix("Bearer ")
    wrong_audience = await client.get(f"{GIT}/{run.id}/info/refs?service=git-upload-pack",
                                      headers={"Authorization": f"Bearer {gateway_token}"})
    assert wrong_audience.status_code == 401  # the gateway login itself is no git token

    stranger = {**headers, "X-Octryx-Session": str(uuid.uuid4())}
    assert (await client.post(f"{GATEWAY}/git-token", headers=stranger)).status_code != 200

    run.status = "completed"
    await db.commit()
    ended = await client.get(f"{GIT}/{run.id}/info/refs?service=git-upload-pack", headers=bearer)
    assert (ended.status_code, ended.json()["reason"]) == (403, "git_run_not_active")


@pytest.mark.asyncio
async def test_the_run_contract_names_the_git_gateway_with_the_platforms_copy(client, auth_headers, db,
                                                                               systems):  # noqa: F811
    from app.services.workflow_runs.workspace.preparation import requirement

    run, _headers, _head, _hidden = await _run_with_a_hidden_branch(client, auth_headers, db, systems)
    needed = await requirement(db, run)
    assert needed["repository"]
    assert needed["git_gateway"] == f"{GIT}/{run.id}"
    # The launcher reads it from the run contract's preparation.
    from app.services.workflow_runs.workspace.preparation import CONTEXT_KEY, contract_view

    run.context = {**dict(run.context or {}), CONTEXT_KEY: {"state": "pending", "spec": needed}}
    assert contract_view(run)["git_gateway"] == f"{GIT}/{run.id}"
    run.context = {**dict(run.context or {}), "local_path": ""}
    assert (await requirement(db, run))["git_gateway"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind, grant_user, expected", [
    ("runner", "runner-account", None),  # the runner acts for the person of its turn
    ("", "runner-account", "folder_not_allowed_on_device"),  # someone else's own device: never
])
async def test_a_runners_folder_is_its_own_for_the_person_of_its_turn(kind, grant_user, expected):
    from types import SimpleNamespace

    from app.models.security.device import DEVICE_STATUS_ACTIVE, UserDevice
    from app.models.security.oauth_provider import OAuthGrant
    from app.services.agent_gateway.repository_root import device_folder_refusal
    from app.services.devices.runner_pool import RUNNER_SERVICE_KIND

    device = SimpleNamespace(status=DEVICE_STATUS_ACTIVE, owner_user_id="runner-account", folders=["/workspace"],
                             service_kind=RUNNER_SERVICE_KIND if kind else None)
    grant = SimpleNamespace(device_id="dev-1", user_id=grant_user)

    class Db:
        async def get(self, model, key):
            return {OAuthGrant: grant, UserDevice: device}[model]

    refused = await device_folder_refusal(Db(), grant_id="g-1", user_id="the-person", root="/workspace/0a1b/repo")
    assert (refused.reason if refused else None) == expected
    outside = await device_folder_refusal(Db(), grant_id="g-1", user_id="the-person", root="/etc")
    assert outside is not None and outside.reason == "folder_not_allowed_on_device"


def test_upload_pack_streams_under_uvloop_also_when_git_stops_reading_early(tmp_path):
    uvloop = pytest.importorskip("uvloop")
    from app.services.agent_gateway import git_upload

    root = tmp_path / "copy"
    root.mkdir()
    _git(root, "init", "-q", "-b", "story")
    (root / "a.txt").write_text("a\n")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-q", "-m", "a")
    head = _git(root, "rev-parse", "HEAD")

    async def collect(stream) -> bytes:
        return b"".join([chunk async for chunk in stream])

    for _ in range(5):
        advertised = uvloop.run(collect(git_upload.advertisement(root, "story")))
        assert f"{head} refs/heads/story".encode() in advertised
        assert b"PACK" in uvloop.run(collect(git_upload.upload_pack(root, "story", _want(head))))
        garbage = uvloop.run(collect(git_upload.upload_pack(root, "story", b"not a pkt-line" * 300_000)))
        assert b"PACK" not in garbage
