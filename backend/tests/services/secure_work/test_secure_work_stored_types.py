from __future__ import annotations

from types import SimpleNamespace
from typing import get_args

import pytest
from sqlalchemy import select

from app.models import WorkPullRequest
from app.services.secure_work.jira.jira_item_details import STATUS_CATEGORIES, jira_detail_fields
from app.services.secure_work.jira.jira_mapping import jira_issue_to_work_item_payload
from app.services.secure_work.jira.stored_types import (
    MappingSource,
    StatusCategory,
    StoredJiraDetails,
    StoredStatusMapping,
)
from app.services.secure_work.pull_requests import host_state, refresh
from app.services.secure_work.pull_requests.host_clients import HostRead
from app.services.secure_work.pull_requests.host_state import (
    aggregate_build_status,
    bitbucket_cloud_state,
    bitbucket_server_state,
    github_state,
)
from app.services.secure_work.pull_requests.host_target import HostTarget
from app.services.secure_work.pull_requests.pull_requests import sync_pull_request
from app.services.secure_work.pull_requests.record_identity import pull_request_identity
from app.services.secure_work.pull_requests.stored_types import (
    BuildStatus,
    HostAuthor,
    HostReviewer,
    NoHostAuthor,
    PullRequestStatus,
    ReviewerApproval,
)
from tests.typed_dict_support import shape_problems
from tests.work_pull_request_refresh_support import _admin, _pr, workspace_item

CLOUD_ISSUE = {
    "key": "OCX-101", "id": "10001",
    "fields": {
        "summary": "Rotate the gateway certificate", "status": {"name": "In Review", "statusCategory": {"key": "done"}},
        "assignee": {"accountId": "acc-1", "displayName": "Example Assignee"},
        "reporter": {"accountId": "acc-2"},
        "watcher": {"watchers": [{"accountId": "acc-3", "displayName": "Example Watcher"}, {"other": 1}]},
        "comment": {"total": 3, "comments": [
            {"id": "501", "author": {"accountId": "acc-1", "displayName": "Example Assignee"},
             "created": "2026-11-20T08:00:00.000+0000",
             "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Done"}]}]}},
            {"author": None, "body": None},
        ]},
    },
}
DC_ISSUE = {"key": "OCX-102", "fields": {"status": {"name": "Open"}, "assignee": {"name": "dc.user"},
                                       "comment": [{"id": 7, "author": {"name": "dc.user"}, "body": "wiki *text*"}]}}


def _config(mapping: dict[str, str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(project_id="p1", id="c1", connector_name="jira", connection_id=None, source_instance="cloud",
                           sync_options_json={"status_state_mapping": mapping or {}}, field_mapping_json={})


def test_jira_detail_fields_are_stored_jira_details():
    for issue, browse_url in ((CLOUD_ISSUE, "https://jira.example.test/browse/OCX-101"), (DC_ISSUE, None),
                              ({"key": "OCX-103"}, None)):
        stored = jira_detail_fields(issue, issue.get("fields") or {}, browse_url)
        assert shape_problems(stored, StoredJiraDetails, "details") == []


def test_the_upserted_payload_carries_stored_jira_details():
    for issue in (CLOUD_ISSUE, DC_ISSUE, {"key": "OCX-103"}):
        source = jira_issue_to_work_item_payload(issue, _config())["source_fields_json"]
        details = {key: source[key] for key in StoredJiraDetails.__annotations__}
        assert shape_problems(details, StoredJiraDetails, "details") == []


def test_every_status_mapping_source_is_a_stored_status_mapping():
    cases = [
        (_config({"in review": "review"}), {"name": "In Review"}, "configured"),
        (_config(), {"name": "Done"}, "builtin"),
        (_config(), {"name": "Waiting for vendor", "statusCategory": {"key": "indeterminate"}}, "status_category"),
        (_config(), {"name": "Waiting for vendor"}, "unmapped"),
    ]
    for config, status, expected in cases:
        payload = jira_issue_to_work_item_payload({"key": "OCX-109", "fields": {"status": status}}, config)
        mapping = payload["source_fields_json"]["status_mapping"]
        assert shape_problems(mapping, StoredStatusMapping, "status_mapping") == []
        assert mapping["source"] == expected


HOST_REPLIES = [
    (bitbucket_server_state({
        "state": "OPEN", "author": {"user": {"name": "author", "displayName": "Example Author"}},
        "reviewers": [{"user": {"name": "rev"}, "status": "APPROVED"}, {"user": {"slug": "rev2"}},
                      {"user": {}, "status": "NEEDS_WORK"}]}), ["SUCCESSFUL"]),
    (bitbucket_cloud_state({
        "state": "SUPERSEDED", "author": {"nickname": "author", "account_id": "acc-1"},
        "participants": [{"role": "REVIEWER", "approved": True, "user": {"account_id": "acc-2"}},
                         {"role": "REVIEWER", "state": "changes_requested", "user": {"nickname": "rev"}},
                         {"role": "PARTICIPANT", "user": {"nickname": "watcher"}}]}), ["FAILED", "SUCCESS"]),
    (github_state({"state": "closed", "merged_at": "2026-11-20T08:00:00Z", "user": {"login": "author"},
                   "requested_reviewers": [{"login": "pending"}]},
                  [{"user": {"login": "rev"}, "state": "CHANGES_REQUESTED"},
                   {"user": {"login": "rev2"}, "state": "COMMENTED"}]), ["INPROGRESS"]),
    (github_state({"state": "open"}, []), []),
]


class _Host:
    def __init__(self, reply: HostRead) -> None:
        self.reply = reply

    async def read(self, target):
        return self.reply


async def _reloaded(db, row_id: str) -> WorkPullRequest:
    db.expire_all()
    return (await db.execute(select(WorkPullRequest).where(WorkPullRequest.id == row_id))).scalar_one()


@pytest.mark.parametrize(("pull_request", "build_states"), HOST_REPLIES)
async def test_a_refreshed_row_stores_the_host_refresh_types(db, monkeypatch, pull_request, build_states):
    async def target(db, row):
        return HostTarget(row.provider, "bitbucket_server", "OCX", "runtime", row.pr_id, None, "conn-1",
                          SimpleNamespace())

    reply = HostRead(pull_request, build_status=aggregate_build_status(build_states))
    monkeypatch.setattr(refresh, "resolve_target", target)
    monkeypatch.setattr(refresh, "client_for", lambda target: _Host(reply))
    row = await _pr(db)
    assert (await refresh.refresh_pull_request(db, row, source="requested"))["ok"]
    await db.commit()
    stored = await _reloaded(db, row.id)
    assert shape_problems(stored.status, PullRequestStatus, "status") == []
    assert shape_problems(stored.reviewers_json, list[HostReviewer], "reviewers_json") == []
    assert shape_problems(stored.approvals_json, list[HostReviewer], "approvals_json") == []
    assert shape_problems(stored.author_json, HostAuthor | NoHostAuthor, "author_json") == []
    assert shape_problems(stored.build_status, BuildStatus | None, "build_status") == []


async def test_the_initial_record_keeps_the_callers_reviewers_and_no_host_fields(db):
    item = await workspace_item(db, "OCX-110")
    url = "https://git.example.test/projects/OCX/repos/runtime/pull-requests/44"
    payload = {"work_item_id": item.id, "identity": pull_request_identity("bitbucket", url, "OCX/runtime", "44"),
               "pr_url": url, "status": "open", "reviewers": ["reviewer-1", {"username": "reviewer-2"}]}
    created = await sync_pull_request(db, current_user=await _admin(db), workspace_id=item.project_id,
                                      payload=payload)
    await db.commit()
    stored = await _reloaded(db, created["id"])
    assert stored.reviewers_json == [{"name": "reviewer-1"}, {"username": "reviewer-2"}]
    assert shape_problems(stored.author_json, NoHostAuthor, "author_json") == []
    assert stored.build_status is None and stored.approvals_json == []


def test_aggregated_build_states_are_build_statuses():
    for states in (["SUCCESSFUL"], ["FAILED", "SUCCESS"], ["INPROGRESS"], ["STOPPED", "SUCCESSFUL"], []):
        assert shape_problems(aggregate_build_status(states), BuildStatus | None, "build") == []


def test_the_literal_vocabularies_are_the_constants_the_code_compares_with():
    assert get_args(StatusCategory) == STATUS_CATEGORIES
    assert set(get_args(MappingSource)) == {"configured", "builtin", "status_category", "unmapped"}
    assert set(get_args(PullRequestStatus)) == {host_state.STATUS_OPEN, host_state.STATUS_MERGED,
                                                host_state.STATUS_DECLINED, host_state.STATUS_CLOSED}
    assert set(get_args(ReviewerApproval)) == {host_state.APPROVED, host_state.NEEDS_WORK,
                                               host_state.CHANGES_REQUESTED, host_state.COMMENTED, host_state.PENDING}
    assert set(get_args(BuildStatus)) == {host_state.BUILD_FAILED, host_state.BUILD_IN_PROGRESS,
                                          host_state.BUILD_STOPPED, host_state.BUILD_SUCCESSFUL}
