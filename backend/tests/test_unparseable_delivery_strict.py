"""Controls audit: a command the parser cannot read stays strict for delivery. Before, an unparseable
command passed the run's SCM-client and push rules (``command_segments(...) or []``)."""

from __future__ import annotations

import pytest

from app.services.workflow_runs.octryx.scm_rules import _bash_run_rules

HOSTS = frozenset({"github.com", "api.github.com"})


@pytest.mark.parametrize(("command", "reason"), [
    ("git push 'x", "push_by_platform"),
    ("git -C . push --force 'x", "push_by_platform"),
    ("git send-pack origin 'x", "push_by_platform"),
    ('gh pr create "unterminated', "platform_action_required"),
    ("curl -X POST https://api.github.com/repos/x 'y", "platform_action_required"),
])
def test_an_unparseable_delivery_command_is_refused(command, reason):
    assert _bash_run_rules(command, hosts=HOSTS).reason == reason


@pytest.mark.parametrize("command", ["git status 'x", "echo 'a", "ls 'x", "curl http://127.0.0.1:8080/ 'y"])
def test_an_unparseable_command_that_delivers_nothing_is_not_refused_here(command):
    assert _bash_run_rules(command, hosts=HOSTS) is None
