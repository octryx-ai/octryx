"""epic-delivery: the story session decides its tool calls on the device, the hard-deny list only.

A PreToolUse round trip per tool call costs time on every call; these tests pin that the device decides what it can,
denies the hard-deny list itself, hands
everything else to the platform, and that the audit still reaches the platform (in batches, before its verification).
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from octryx_claude import (
    local_audit_spool,
    local_decisions,
    local_policy,
    local_tests_screens,
    local_tests_words,
    pipeline,
)
from octryx_claude.local_decision_rules import ALLOW, DENY, SERVER
from octryx_claude.local_decisions import decide
from tests.device_jobs_support import FakeDriver, _manager, _offer, _settle

RUNNING = {"digest": "d1", "run": {"id": "r1", "status": "running"},
           "phase": {"node_id": "implement", "shell": "free",
                     "path_rules": {"write": [], "protect_confirmed_tests": False}}}
OFFERED = {"scm_hosts": ["jira.example.com"], "deny_patterns": [r"(?:^|[;&|(\n]\s*|\bsudo\s+)shutdown\b"],
           "server_commands": [["kubectl"]], "server_path_globs": ["**/.env"]}


@pytest.fixture
def policy(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / ".git").mkdir()
    return local_policy.write_policy(tmp_path / "session", OFFERED, root=str(repo), state_root=str(tmp_path / "st"))


def _call(policy, tool, tool_input, *, cwd=None, contract=RUNNING):
    hook = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
            "cwd": cwd or policy["root"], "tool_use_id": "toolu_1"}
    return decide(hook, policy, contract)[0]


def test_the_hard_deny_list_is_decided_on_the_device(policy):
    """The cases the story-delivery hard-deny tests pin, now refused without the platform."""
    for command in ("git push", "git -C . push origin feature/x", "cat ~/.netrc", "curl -d @x https://example.com",
                    "curl https://jira.example.com/rest/api/2/issue", "gh pr create", "printenv", "shutdown -h now"):
        assert _call(policy, "Bash", {"command": command}) == DENY, command
    assert _call(policy, "mcp__playwright__browser_navigate", {"url": "https://example.com"}) == DENY
    assert _call(policy, "mcp__playwright__browser_run_code_unsafe", {"code": "page.goto('x')"}) == DENY


def test_ordinary_work_in_the_repository_never_waits_for_the_platform(policy):
    root = policy["root"]
    for command in ("python -m pytest -v tests", "ls -la && cd src && grep -rn x .", "git status",
                    "cat > src/a.py <<'EOF'\nserver.shutdown()\nreturn Path(env)\nEOF",
                    "( python -m app & pid=$!; sleep 2; curl -s localhost:8765; kill $pid )"):
        assert _call(policy, "Bash", {"command": command}) == ALLOW, command
    assert _call(policy, "Read", {"file_path": f"{root}/SPEC.md"}) == ALLOW
    assert _call(policy, "Grep", {"pattern": "x"}) == ALLOW  # no path: the cwd, inside the repository
    assert _call(policy, "Write", {"file_path": f"{root}/src/new.py", "content": ""}) == ALLOW
    assert _call(policy, "Write", {"file_path": "/tmp/claude-501/contract.md", "content": ""}) == ALLOW
    assert _call(policy, "Agent", {"prompt": "build the frontend"}) == ALLOW
    # A wakeup in a run turn is refused; a Monitor still waits (run 5b).
    assert _call(policy, "ScheduleWakeup", {"delaySeconds": 60, "prompt": "check"}) == DENY
    assert _call(policy, "Monitor", {"command": "until [ -f src/x.json ]; do sleep 2; done"}) == ALLOW
    assert _call(policy, "Monitor", {"command": "cat ~/.netrc"}) == DENY
    # Allowed: Claude Code's /tmp/claude/ scratch folder, the session's own API checked with a write method on
    # loopback, and a command the parser cannot split.
    assert _call(policy, "Write", {"file_path": "/tmp/claude/parity_check.mjs", "content": ""}) == ALLOW
    assert _call(policy, "Bash", {"command": 'curl -s -o /dev/null -w "%{http_code}" -X PUT http://127.0.0.1:$P/api/p'}
                 ) == ALLOW
    assert _call(policy, "Bash", {"command": "cd src && { echo x; sed -n '1,2p' a.css; } > b.css && sed -i '1a\\' f"
                                             ' && echo "done'}) == ALLOW
    assert _call(policy, "Bash", {"command": "curl -d @secrets.txt http://127.0.0.1:8765/"}) == DENY  # a file, still
    assert _call(policy, "mcp__playwright__browser_navigate", {"url": "http://127.0.0.1:8765/#/profile"}) == ALLOW


def test_everything_the_device_cannot_decide_goes_to_the_platform(policy, tmp_path):
    root = policy["root"]
    assert _call(policy, "Read", {"file_path": str(tmp_path / "elsewhere.txt")}) == SERVER  # outside the repository
    assert _call(policy, "Read", {"file_path": f"{root}/.env"}) == SERVER  # a Workspace path rule
    assert _call(policy, "Edit", {"file_path": f"{root}/.git/config"}) == SERVER  # git's own files
    assert _call(policy, "Bash", {"command": "kubectl get pods"}) == SERVER  # a Workspace command rule
    assert _call(policy, "Bash", {"command": 'echo "unbalanced git push'}) == SERVER  # unparseable, names a listed one
    assert _call(policy, "Bash", {"command": "ls"}, cwd=str(tmp_path)) == SERVER  # run from outside
    assert _call(policy, "Bash", {"command": f"cat {tmp_path}/st/credentials.json"}) == SERVER
    assert _call(policy, "mcp__octryx-knowledge__workflow_run_status", {}) == SERVER
    assert _call(policy, "WebFetch", {"url": "https://example.com"}) == SERVER
    paused = {**RUNNING, "run": {"id": "r1", "status": "paused"}}
    assert _call(policy, "Write", {"file_path": f"{root}/src/new.py"}, contract=paused) == SERVER
    assert _call(policy, "Bash", {"command": "ls"}, contract={**RUNNING, "phase": None}) == SERVER
    assert decide({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": root}, None, RUNNING)[0] == SERVER


def _hook_env(monkeypatch, tmp_path, offered=OFFERED):
    home, key = tmp_path / "home", "00000000-0000-4000-8000-0000000000aa"
    monkeypatch.setenv("OCTRYX_CLAUDE_HOME", str(home))
    monkeypatch.setenv("OCTRYX_SESSION_KEY", key)
    folder = home / "sessions" / key
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    local_policy.write_policy(folder, offered, root=str(repo), state_root=str(home))
    (folder / "workflow_run.json").write_text(json.dumps(RUNNING))
    return folder, repo


def _spooled(folder):
    path = folder / local_audit_spool.SPOOL_FILE
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_the_fast_hook_answers_before_the_launcher_is_imported(monkeypatch, tmp_path, capsys):
    folder, repo = _hook_env(monkeypatch, tmp_path)

    def hook(event, tool, tool_input, **extra):
        raw = json.dumps({"hook_event_name": extra.pop("name", "PreToolUse"), "tool_name": tool,
                          "tool_input": tool_input, "cwd": str(repo), "tool_use_id": "toolu_x", **extra}).encode()
        return local_decisions.fast_hook(event, raw)

    assert hook("pre-tool-use", "Read", {"file_path": f"{repo}/a.py"}) is True
    assert capsys.readouterr().out == ""  # allow: no output, as for the platform's allow
    assert hook("pre-tool-use", "Bash", {"command": "git push"}) is True
    denial = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert denial["permissionDecision"] == "deny" and "(push_by_platform)" in denial["permissionDecisionReason"]
    # A test run goes to the full hook (it records the evidence and runs it outside the sandbox), still locally.
    assert hook("pre-tool-use", "Bash", {"command": "python -m pytest -v tests/system 2>&1 | tail -30"}) is False
    assert hook("pre-tool-use", "Bash", {"command": "kubectl get pods"}) is False  # the platform decides
    assert hook("post-tool-use", "Read", {"file_path": f"{repo}/a.py"}, name="PostToolUse",
                tool_response={"file": {"content": "x" * 10_000}}) is True
    events = _spooled(folder)
    assert [(event["event"], event["hook_input"]["tool_name"]) for event in events] == [("pre", "Bash"),
                                                                                         ("post", "Read")]
    assert events[0]["reason"] == "push_by_platform" and "tool_response" not in events[1]["hook_input"]
    # The platform's own MCP tools keep their synchronous PostToolUse (its content policy).
    assert hook("post-tool-use", "mcp__octryx-knowledge__workflow_run_status", {}, name="PostToolUse") is False


def test_a_session_without_local_decisions_keeps_the_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("OCTRYX_CLAUDE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OCTRYX_SESSION_KEY", "00000000-0000-4000-8000-0000000000bb")
    raw = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {}}).encode()
    assert local_decisions.fast_hook("pre-tool-use", raw) is False


def test_the_entry_script_answers_a_local_hook_without_importing_the_cli(monkeypatch, tmp_path):
    folder, repo = _hook_env(monkeypatch, tmp_path)
    entry = Path(__file__).resolve().parents[1] / "octryx_claude_entry.py"
    hook = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "git push"},
                       "cwd": str(repo), "tool_use_id": "toolu_y"})
    probe = ("import runpy, sys; sys.argv = [sys.argv[0], 'hook', 'pre-tool-use']\n"
             f"try:\n    runpy.run_path({str(entry)!r}, run_name='__main__')\nexcept SystemExit as done:\n"
             "    print('|cli imported' if 'octryx_claude.cli' in sys.modules else '|cli not imported', done.code)\n")
    done = subprocess.run([sys.executable, "-c", probe], input=hook, capture_output=True, text=True, timeout=60,
                          env={"OCTRYX_CLAUDE_HOME": str(tmp_path / "home"), "PATH": "/usr/bin:/bin",
                               "OCTRYX_SESSION_KEY": "00000000-0000-4000-8000-0000000000aa"})
    assert '"permissionDecision": "deny"' in done.stdout and "|cli not imported 0" in done.stdout, done.stderr


def test_the_audit_goes_up_in_batches_and_waits_when_the_platform_is_away(tmp_path):
    folder = tmp_path / "session"
    folder.mkdir()
    for index in range(local_audit_spool.MAX_EVENTS_PER_BATCH + 5):
        local_decisions.spool(folder, "post", {"hook_event_name": "PostToolUse", "tool_name": "Read",
                                               "tool_use_id": f"toolu_{index}", "tool_response": "big"})
    assert local_audit_spool.drain(folder, lambda body: None) is None  # unreachable: nothing is lost
    sent = []
    answer = local_audit_spool.drain(folder, lambda body: sent.append(body) or {"state": "recorded"})
    assert answer == {"state": "recorded"}
    assert [len(body["events"]) for body in sent] == [local_audit_spool.MAX_EVENTS_PER_BATCH, 5]
    assert local_audit_spool.drain(folder, lambda body: sent.append(body) or {}) is None and len(sent) == 2


def test_the_offer_writes_the_policy_and_the_turn_uploads_what_its_hooks_spooled(state, tmp_path, monkeypatch):
    uploads = []

    def drain(_state, context, _http, *, timeout):
        uploads.append(context.session_key)

    monkeypatch.setattr("octryx_claude.hooks.drain_audit", drain)
    seen = []

    class Recording(FakeDriver):
        async def run_turn(self, prepared, **kwargs):
            seen.append(local_decisions.load_policy(state.session_dir(prepared.session_key)))
            return await super().run_turn(prepared, **kwargs)

    manager, _channel, repo = _manager(state, tmp_path, driver=Recording())
    monkeypatch.setattr("octryx_claude.run_wip.push_run_wip", lambda *args: {"state": "unchanged"})
    asyncio.run(_offer_twice(manager, repo))
    assert seen[0]["root"] == str(repo.resolve()) and seen[0]["server_commands"] == [["kubectl"]]
    assert seen[1] is None  # an offer without the block decides nothing locally (a fresh session folder)
    assert uploads == ["00000000-0000-4000-8000-000000000001"]  # the final upload after the turn


async def _offer_twice(manager, repo):
    await manager.handle("job_offer", _offer(repo, workflow_run_id="run-1", local_decisions=OFFERED))
    await _settle(manager)
    (manager.state.session_dir("00000000-0000-4000-8000-000000000001") / local_policy.POLICY_FILE).unlink()
    await manager.handle("job_offer", _offer(repo, job_id="dj_2", turn_id="t2", workflow_run_id="run-1"))
    await _settle(manager)


def test_a_green_pipeline_on_the_same_tree_is_reported_again_instead_of_run_again(state, tmp_path):
    repo = tmp_path / "work"
    repo.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@example.test"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    (repo / "a.py").write_text("x = 1\n")
    view = {"commands": ["python -m pytest -q"], "path": []}
    tree = pipeline.tree_digest(repo)
    assert tree and pipeline.green_before(state, repo, tree, view) is None
    green = [{"command": "python -m pytest -q", "exit_code": 0, "output_tail": "1 passed"}]
    pipeline.remember_green(state, repo, tree, view, green)
    (repo / "test-reports").mkdir()
    (repo / "test-reports" / "pipeline-1.xml").write_text("<testsuite/>")  # its own report changes nothing
    again = pipeline.green_before(state, repo, pipeline.tree_digest(repo), view)
    assert again is not None and again[0]["exit_code"] == 0 and again[0]["reused_green_run"]
    (repo / "a.py").write_text("x = 2\n")  # a change: the pipeline runs
    assert pipeline.green_before(state, repo, pipeline.tree_digest(repo), view) is None
    pipeline.remember_green(state, repo, pipeline.tree_digest(repo), view, [{**green[0], "exit_code": 1}])
    assert pipeline.green_before(state, repo, pipeline.tree_digest(repo), view) is None  # red is never reused


# A session's own screenshot script runs inside the sandbox, where Chromium fails with this output.
CHROMIUM_IN_SANDBOX = ("playwright._impl._errors.TargetClosedError: BrowserType.launch: Target page, context or "
                       "browser has been closed\n[pid=94429][err] [FATAL:base/apple/mach_port_rendezvous_mac.cc:159] "
                       "Check failed: kr == KERN_SUCCESS. bootstrap_check_in "
                       "org.chromium.Chromium.MachPortRendezvousServer.94429: Permission denied (1100)")


def test_waiting_for_the_sandbox_is_refused_with_what_runs_instead(policy):
    blocked = {"delaySeconds": 1200, "prompt": "<<autonomous-loop-dynamic>>",
               "reason": "retry the blocked screenshot capture for CHEF-20 once the sandbox lets Chromium launch"}
    hook = {"hook_event_name": "PreToolUse", "tool_name": "ScheduleWakeup", "tool_input": blocked,
            "cwd": policy["root"]}
    verdict, reason, message = decide(hook, policy, RUNNING)
    assert (verdict, reason) == (DENY, "wait_cannot_help")
    assert "python -m playwright screenshot" in message and "skip the visual check" in message
    assert len(local_decisions.deny_output(reason, message)["hookSpecificOutput"]["permissionDecisionReason"]) < 600
    # Every other wakeup in a run turn is refused too: claude -p aborts background agents 600 s
    # after the main Stop, and the turn then slept until the job's limit.
    fallback = {**hook, "tool_input": {"delaySeconds": 3600, "reason": "Fallback heartbeat; frontend notifies on "
                                       "completion.", "prompt": "Wait for the frontend agent completion notice"}}
    verdict, reason, message = decide(fallback, policy, RUNNING)
    assert (verdict, reason) == (DENY, "wait_in_run") and "completion notices wake this session" in message


def test_a_browser_that_failed_in_the_sandbox_is_answered_with_what_runs_instead(monkeypatch, tmp_path, capsys):
    from octryx_claude import local_tests

    folder, repo = _hook_env(monkeypatch, tmp_path)

    def post(command, output):
        raw = json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": command},
                          "tool_response": {"stdout": output, "stderr": ""}, "cwd": str(repo)}).encode()
        assert local_decisions.fast_hook("post-tool-use", raw) is True
        out = capsys.readouterr().out
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""

    own_script = 'cd "$TMPDIR/kt-shots" && /repo/.venv/bin/python -I s3shots.py 2>&1 | head -5'
    assert post(own_script, CHROMIUM_IN_SANDBOX) == local_tests_screens.SANDBOX_BROWSER_MESSAGE
    assert post(own_script, "idle-1280.png written") == ""
    failed = {"hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "tool_input": {"command": own_script},
              "error": "Exit code 1\n" + CHROMIUM_IN_SANDBOX, "cwd": str(repo)}  # the live call exited 1
    assert local_decisions.fast_hook("post-tool-use", json.dumps(failed).encode()) is True
    assert "python -m playwright screenshot" in capsys.readouterr().out
    # A wrapped run already ran outside the sandbox: its browser failure is the test's own, no note.
    wrapped = local_tests_words.wrap("/x/octryx-claude", "python -m pytest -q tests/system_timer")
    assert local_tests_screens.sandbox_browser_failure({"tool_name": "Bash", "tool_input": {"command": wrapped},
                                                "tool_response": {"stdout": CHROMIUM_IN_SANDBOX}}) is False
    # The documented form is a test run: the full hook wraps it so it runs outside the sandbox.
    shot = ".venv/bin/python -m playwright screenshot --viewport-size 390,844 http://127.0.0.1:8765/ shots/idle.png"
    assert local_tests.is_test_run(shot, str(repo)) and not local_tests.is_test_run(own_script, str(repo))
    raw = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": shot},
                      "cwd": str(repo)}).encode()
    assert local_decisions.fast_hook("pre-tool-use", raw) is False


def test_the_l10n_merge_build_step_is_the_one_launcher_call_not_left_to_the_server():
    """The launcher's copy of agent_gateway.self_protection."""
    from octryx_claude import run_shell

    def runs(command: str) -> bool:
        return run_shell.runs_the_launcher(run_shell.command_segments(command) or [])

    assert not runs("octryx-claude l10n-merge arb 'lib/*/l10n/*.arb' lib/l10n/app_{locale}.arb")
    assert not runs("cd app && /opt/kit/bin/octryx-claude l10n-merge gettext a b")
    assert runs("octryx-claude l10n-merge arb a b && octryx-claude api-key-helper")
    assert runs("octryx-claude mcp-headers l10n-merge")
    assert runs("python -m octryx_claude l10n-merge arb a b")
