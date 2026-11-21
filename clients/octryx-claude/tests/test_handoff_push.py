"""The branch push policy, the bundle fallback, secret scan refusals and the pending takeover poll."""

from __future__ import annotations

import json

import pytest

from tests.handoff_support import Platform, git, hand_over, remote_branches, repos  # noqa: F401

from .gitrepo import requires_git

pytestmark = requires_git


AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


def test_the_branch_is_pushed_only_to_a_registered_remote_under_push_branch(state, repos):  # noqa: F811
    platform = Platform(repositories=[str(repos["remote"])])
    report = hand_over(state, platform, repos["user"], note="tests red")
    branch = "octryx-handoff/BRD-6/Anna-20261006-1030"

    assert report.ok and report.items[0].pushed and report.items[0].bundle_id == ""
    assert remote_branches(repos["remote"]) == ["refs/heads/main", f"refs/heads/{branch}"]  # no other ref
    commit = platform.commits[0]
    assert commit["repo"]["branch"] == branch and "bundle_id" not in commit["repo"]
    assert commit["repo"]["wip_commit"] == git(repos["remote"], "rev-parse", f"refs/heads/{branch}")
    assert commit["note"] == "tests red" and commit["git"]["excluded_files"][0] == ".aws/credentials"
    assert not any(path.endswith("/attachments") for path in platform.paths())


@pytest.mark.parametrize(("push", "registered"), [("bundle_only", True), ("branch", False)])
def test_no_push_without_policy_or_to_an_unregistered_remote_uses_the_bundle(state, repos, push, registered):  # noqa: F811
    platform = Platform(push=push, repositories=[str(repos["remote"])] if registered else ["https://elsewhere/x.git"])
    report = hand_over(state, platform, repos["user"])
    assert report.ok and not report.items[0].pushed and report.items[0].bundle_id == "bundle-1"
    assert remote_branches(repos["remote"]) == ["refs/heads/main"]
    assert platform.commits[0]["repo"]["bundle_id"] == "bundle-1"
    assert platform.uploads["bundle-1"].startswith(b"# v")


def test_a_failed_push_falls_back_to_the_bundle_and_push_off_hands_over_the_document_only(state, repos, tmp_path):  # noqa: F811
    git(repos["user"], "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    fallback = Platform(repositories=[str(tmp_path / "gone.git")])
    report = hand_over(state, fallback, repos["user"])
    assert report.ok and not report.items[0].pushed and report.items[0].bundle_id == "bundle-1"
    off = Platform(push="off", repositories=[str(tmp_path / "gone.git")])
    report = hand_over(state, off, repos["user"])  # the same minute: a free branch name, never a moved one
    assert report.ok and off.uploads == {} and "bundle_id" not in off.commits[0]["repo"]
    assert off.commits[0]["repo"]["branch"] == "octryx-handoff/BRD-6/Anna-20261006-1030-2"


def test_a_secret_scan_refusal_stops_that_handoff_with_a_clear_message(state, repos):  # noqa: F811
    platform = Platform(push="bundle_only", upload_status=422)
    report = hand_over(state, platform, repos["user"])
    assert not report.ok and platform.commits == []
    assert "contains a secret" in report.lines()[0] and AWS_KEY not in report.summary()


def test_all_covers_every_held_item_with_one_wip_commit(state, repos):  # noqa: F811
    items = [{"id": "item-6", "key": "BRD-6", "title": "A"}, {"id": "item-7", "key": "BRD-7", "title": "B"}]
    platform = Platform(repositories=[str(repos["remote"])], items=items)
    report = hand_over(state, platform, repos["user"], all_items=True)
    assert [item.key for item in report.items] == ["BRD-6", "BRD-7"]
    assert json.loads(platform.requests[0].content) == {"key": None, "all": True}
    assert {commit["repo"]["wip_commit"] for commit in platform.commits} == {platform.commits[0]["repo"]["wip_commit"]}
    assert [commit["repo"]["branch"] for commit in platform.commits] == [
        "octryx-handoff/BRD-6/Anna-20261006-1030", "octryx-handoff/BRD-7/Anna-20261006-1030"]


def test_a_pending_takeover_is_polled_until_someone_takes_over(state, repos):  # noqa: F811
    platform = Platform(repositories=[str(repos["remote"])],
                        takeover={"id": "t1", "status": "pending", "to": {"user": {"display_name": "Ben"}}})
    report = hand_over(state, platform, repos["user"], poll_seconds=30)
    assert platform.polls == 1 and report.items[0].takeover == "taken over by the agent of Ben"
