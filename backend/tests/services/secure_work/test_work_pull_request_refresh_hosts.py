"""Each host's pull request state maps explicitly, build statuses aggregate, host targets resolve or refuse, and the Bitbucket Server client reads the PR and its builds."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services.secure_work.pull_requests.host_clients import BitbucketServerHost
from app.services.secure_work.pull_requests.host_state import (
    HostStateError,
    aggregate_build_status,
    bitbucket_cloud_state,
    bitbucket_server_state,
    github_state,
)
from app.services.secure_work.pull_requests.host_target import (
    HostTarget,
    PullRequestHostError,
    resolve_target,
)
from app.tools.bitbucket_impl import _bitbucket_internal_network
from tests.work_pull_request_refresh_support import _pr

# --- mapping -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("state", "expected"), [("OPEN", "open"), ("MERGED", "merged"), ("DECLINED", "declined")])
def test_bitbucket_server_states_map_explicitly(state, expected):
    pr = {"state": state, "reviewers": [
        {"user": {"name": "alice", "displayName": "Alice"}, "approved": True, "status": "APPROVED"},
        {"user": {"name": "bob", "displayName": "Bob"}, "status": "NEEDS_WORK"}],
        "fromRef": {"displayId": "feature/x", "latestCommit": "a" * 40}, "updatedDate": 1_700_000_000_000}
    mapped = bitbucket_server_state(pr)
    assert mapped.status == expected
    assert [item["approval"] for item in mapped.reviewers] == ["approved", "needs_work"]
    assert [item["username"] for item in mapped.approvals] == ["alice"]
    assert mapped.source_updated_at == datetime(2023, 11, 14, 22, 13, 20)


def test_bitbucket_cloud_superseded_is_closed_and_unknown_state_refuses():
    pr = {"state": "SUPERSEDED", "participants": [
        {"role": "REVIEWER", "approved": False, "state": "changes_requested",
         "user": {"account_id": "557058:abc", "nickname": "carol", "display_name": "Carol"}},
        {"role": "PARTICIPANT", "user": {"account_id": "x"}}], "updated_on": "2026-11-01T10:00:00+00:00"}
    mapped = bitbucket_cloud_state(pr)
    assert mapped.status == "closed"
    assert mapped.reviewers == [{"username": "carol", "name": "Carol", "account_id": "557058:abc",
                                 "approval": "needs_work"}]
    with pytest.raises(HostStateError) as refused:
        bitbucket_cloud_state({"state": "WEIRD"})
    assert refused.value.code == "unknown_host_state"


def test_github_merged_closed_and_review_states():
    reviews = [{"user": {"login": "dave"}, "state": "CHANGES_REQUESTED"},
               {"user": {"login": "dave"}, "state": "APPROVED"},
               {"user": {"login": "erin"}, "state": "APPROVED"}]
    merged = github_state({"state": "closed", "merged": True, "requested_reviewers": [{"login": "erin"}]}, reviews)
    assert merged.status == "merged"
    assert {item["username"]: item["approval"] for item in merged.reviewers} == {"erin": "pending", "dave": "approved"}
    assert github_state({"state": "closed", "merged_at": None}, []).status == "closed"
    assert github_state({"state": "open"}, []).status == "open"


def test_build_status_aggregation():
    assert aggregate_build_status([]) is None
    assert aggregate_build_status(["SUCCESSFUL", "SUCCESSFUL"]) == "successful"
    assert aggregate_build_status(["SUCCESSFUL", "INPROGRESS"]) == "in_progress"
    assert aggregate_build_status(["INPROGRESS", "FAILED"]) == "failed"
    with pytest.raises(HostStateError):
        aggregate_build_status(["SOMETHING"])


# --- target resolution and host client -----------------------------------------------------------------------


async def test_target_resolution_refuses_explicitly(db, monkeypatch):
    from app.services.named_connections.service_config import ConnectionRefusalError
    from app.services.secure_work.pull_requests import host_target

    gitlab = await _pr(db, number="9", provider="gitlab")
    with pytest.raises(PullRequestHostError) as refused:
        await resolve_target(db, gitlab)
    assert refused.value.code == "provider_unsupported"

    async def no_connection(*args, **kwargs):
        raise ConnectionRefusalError({"code": "connection_ambiguous", "error": "several"})

    monkeypatch.setattr(host_target, "service_connection_config", no_connection)
    row = await _pr(db, number="10")
    with pytest.raises(PullRequestHostError) as refused:
        await resolve_target(db, row)
    assert refused.value.code == "connection_refused"
    assert refused.value.details == {"router_code": "connection_ambiguous"}


async def test_a_record_without_its_owner_path_is_unresolved(db):
    row = await _pr(db, number="11", provider="github", project_key="")
    with pytest.raises(PullRequestHostError) as refused:
        await resolve_target(db, row)
    assert refused.value.code == "repository_unresolved"


async def test_bitbucket_server_client_reads_the_pr_and_its_build(monkeypatch):
    sha = "b" * 40
    pr = {"id": 12, "version": 3, "state": "OPEN", "title": "T", "fromRef": {"latestCommit": sha},
          "toRef": {"displayId": "main"}, "reviewers": [{"user": {"name": "alice"}, "status": "UNAPPROVED"}]}

    async def get(context, path, *, params=None):
        if path.endswith(f"/commits/{sha}"):
            return {"values": [{"state": "SUCCESSFUL"}, {"state": "FAILED"}]}
        return pr

    monkeypatch.setattr(_bitbucket_internal_network, "_bitbucket_json_get", get)
    target = HostTarget("bitbucket", "bitbucket_server", "OCX", "runtime", "12", None, "default", SimpleNamespace())
    client = BitbucketServerHost()
    read = await client.read(target)
    assert read.pull_request.status == "open" and read.build_status == "failed" and read.build_error is None
