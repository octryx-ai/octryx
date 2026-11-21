"""A device job session is refused a folder whose remote is not the run's repository or lies outside the allowed folders, registration is refused for a run its owner may not follow, and a terminal session with another repository cannot attach to the run."""

from __future__ import annotations

import uuid

import pytest

from app.models import WorkflowRun
from tests.device_job_session_parity_support import (  # noqa: F401
    GATEWAY,
    _b_at_tests_first,
    _binding,
    _device,
    _gateway,
    _headers,
    _register,
    _server_pipeline,
)
from tests.knowledge_evidence_seed_support import fetch_user, seed_member
from tests.phased_workflow_fixtures import admin_user
from tests.workflow_acceptance_support import systems  # noqa: F401 - the stubbed Jira and GitHub fixture


@pytest.mark.asyncio
async def test_a_folder_whose_remote_is_not_the_runs_repository_or_outside_the_allowed_folders_is_refused(
        client, auth_headers, db, systems):  # noqa: F811 - the imported fixture
    project, run_id, working_copy = await _b_at_tests_first(client, auth_headers, db, systems)
    admin = await admin_user(db)
    token = await _device(db, admin, [str(working_copy.parent)])

    async def bind(binding: dict) -> tuple[int, dict, object]:
        headers = _headers(token, project.id, run_id)
        assert (await _register(client, headers))["status"] == 200
        answer = await client.post(f"{GATEWAY}/repository", headers=headers, json=binding)
        gateway = await _gateway(db, headers)
        await db.refresh(gateway)
        return answer.status_code, answer.json(), gateway

    for remote in ("https://scm.stub.test/acme/other.git",  # another repository on the same host
                   "https://github.com/acme/pay.git",  # the same path on a host the connection does not serve
                   "git@evil.example:acme/pay.git"):
        status, body, gateway = await bind(_binding(str(working_copy), remote))
        assert (status, body["reason"]) == (403, "repository_not_run_repository"), (remote, body)
        assert "repository_binding" not in gateway.metadata_
    status, body, gateway = await bind(_binding("/Users/someone/elsewhere/pay"))
    assert (status, body["reason"]) == (403, "folder_not_allowed_on_device")
    assert "repository_binding" not in gateway.metadata_
    status, body, _ = await bind({k: v for k, v in _binding(str(working_copy)).items() if k != "root"})
    assert (status, body["reason"]) == (403, "repository_root_missing")
    # A Bitbucket-style ssh remote of the right repository on the connection's host is the same repository.
    status, body, gateway = await bind(_binding(str(working_copy), "ssh://git@scm.stub.test:7999/ACME/pay.git"))
    assert status == 200 and gateway.metadata_["repository_binding"]["root"] == str(working_copy), body


@pytest.mark.asyncio
async def test_registration_refuses_a_run_the_device_owner_may_not_follow(client, auth_headers, db, systems):  # noqa: F811
    project, run_id, working_copy = await _b_at_tests_first(client, auth_headers, db, systems)
    member = await fetch_user(db, await seed_member(db, workspace_id=project.id, role="member"))
    token = await _device(db, member, [str(working_copy.parent)])
    refused = await _register(client, _headers(token, project.id, run_id))
    assert (refused["status"], refused["reason"]) == (403, "run_read_only")
    admin = await admin_user(db)
    unknown = await _register(client, _headers(await _device(db, admin, ["/tmp"]), project.id, str(uuid.uuid4())))
    assert (unknown["status"], unknown["reason"]) == (403, "unknown_run")


@pytest.mark.asyncio
async def test_a_terminal_session_with_another_repository_cannot_attach_to_the_run(client, auth_headers, db, systems):  # noqa: F811
    """The order binding → attach never skips the check (a terminal binds first, then selects the run)."""
    from app.services.agent_gateway.identity import GatewayIdentity
    from app.services.agent_gateway.sessions import get_or_create_gateway_session
    from app.services.workflow_runs.octryx.attach import attach
    from app.services.workflow_runs.records import WorkflowRunError

    project, run_id, working_copy = await _b_at_tests_first(client, auth_headers, db, systems)
    admin = await admin_user(db)
    identity = GatewayIdentity(user=admin, grant_id="gw", oauth_client_id="octryx", workspace_id=project.id,
                               session_key=str(uuid.uuid4()), work_item_key="")
    gateway = await get_or_create_gateway_session(db, identity)
    gateway.metadata_ = {**gateway.metadata_, "repository_binding": {
        "root": str(working_copy), "remote": "https://scm.stub.test/acme/other"}}
    await db.flush()
    run = await db.get(WorkflowRun, run_id)
    with pytest.raises(WorkflowRunError) as refused:
        await attach(db, gateway_session=gateway, user=admin, workspace_id=project.id, run=run)
    assert refused.value.code == "repository_not_run_repository"
    gateway.metadata_ = {**gateway.metadata_, "repository_binding": {
        "root": str(working_copy), "remote": "https://scm.stub.test/acme/pay"}}
    await db.flush()
    assert (await attach(db, gateway_session=gateway, user=admin, workspace_id=project.id, run=run)).id == run_id
