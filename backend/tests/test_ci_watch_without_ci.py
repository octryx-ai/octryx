"""A repository without CI never reports a build: after the grace the CI watch goes on."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from app.services.workflow_runs.platform.ci import CiResult
from app.services.workflow_runs.watch import NO_CI_GRACE_MINUTES, _no_ci_reported
from app.time_utils import utc_now


def _run(minutes_ago: float):
    entered = (utc_now().replace(tzinfo=None) - timedelta(minutes=minutes_ago)).isoformat()
    return SimpleNamespace(node_state={"entered_at": entered})


def test_no_build_after_the_grace_means_no_ci_and_a_real_state_never_does():
    none = CiResult("bitbucket", "unknown", reason="no build status for the branch head")
    assert _no_ci_reported(_run(NO_CI_GRACE_MINUTES + 1), none)
    assert not _no_ci_reported(_run(1), none)  # still within the grace: CI may start late
    running = CiResult("bitbucket", "running", reason="")
    assert not _no_ci_reported(_run(NO_CI_GRACE_MINUTES + 1), running)  # a real build in progress
    not_yet = CiResult("bitbucket", "running", reason="no build status for the pushed commit yet")
    assert _no_ci_reported(_run(NO_CI_GRACE_MINUTES + 1), not_yet)  # a repository without CI answers like this
    unreachable = CiResult("native", "unknown", reason="ConnectError: unreachable")
    assert not _no_ci_reported(_run(NO_CI_GRACE_MINUTES + 1), unreachable)  # an outage is no "no CI"


async def test_actions_the_connection_cannot_read_count_as_no_ci_after_the_grace(monkeypatch):
    """A connection that gets 403 on the Actions runs list must not leave the run waiting at the ci node for ever.
    403/404 is "no Actions run readable", so the no-CI grace applies; other errors do not."""
    from app.services.workflow_runs.platform import ci

    async def fake_dispatch(_db, _run, _tool, _args, **_kwargs):
        return SimpleNamespace(ok=False, result={}, reason=answer)

    monkeypatch.setattr(ci, "dispatch_tool", fake_dispatch)
    run = SimpleNamespace(context={"head_sha": "e806735bda91eb37"}, branch="bugfix/x", repository="github.com/o/b")
    ref = SimpleNamespace(args=lambda: {"owner": "o", "repo": "b"})
    answer = "Tool execution failed: Client error '403 Forbidden' for url 'https://api.github.com/repos/o/b/actions/runs'"
    forbidden = await ci._github(None, run, ref, "")
    assert forbidden.state == "unknown" and "cannot read GitHub Actions (403 Forbidden)" in forbidden.reason
    assert _no_ci_reported(_run(NO_CI_GRACE_MINUTES + 1), forbidden)
    answer = "Tool execution failed: Server error '502 Bad Gateway'"
    outage = await ci._github(None, run, ref, "")
    assert not _no_ci_reported(_run(NO_CI_GRACE_MINUTES + 1), outage)
