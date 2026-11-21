"""The default shell runs normal developer work also where confirmed tests are protected; strictness is the team's
choice. `cd e2e/node && npm test` must not be refused and pause the run, and a heredoc into a test file is not
refused with the generic text."""

from app.services.agent_gateway.tool_check import REASON_ALLOWED_BY_DEFAULT
from app.services.workflow_runs.octryx.hooks import test_prefixes as prefixes_of
from app.services.workflow_runs.octryx.phase_rules import _tool_decision

NPM = "cd e2e/node && npm test 2>&1 | tail -15"
HEREDOC = "cat >> tests/test_split.py <<'EOF'\ndef test_x():\n    assert True\nEOF"


def _phase(**extra) -> dict:
    return {"title": "Minimal fix", "capability_class": "code_change",
            "tools": {"allow": ["edit_workspace_file", "run_test_suite"], "deny": []},
            "path_rules": {"write": [], "create": [], "protect_confirmed_tests": True}, **extra}


def _decide(phase: dict, command: str, defaults: dict | None = None):
    return _tool_decision(phase, "Bash", command, prefixes_of(None), defaults={} if defaults is None else defaults)


def test_a_phase_that_protects_confirmed_tests_runs_the_default_shell():
    for command in (NPM, HEREDOC, "grep -rniE 'grind(Setting|er)?\\b' lib; git log --oneline | head -3"):
        decided = _decide(_phase(), command)
        assert decided is None or decided.reason == REASON_ALLOWED_BY_DEFAULT, command


def test_the_team_makes_a_node_or_the_workspace_strict_and_a_shell_write_is_told_to_use_write():
    strict = _decide(_phase(shell="strict"), HEREDOC)
    assert strict.decision == "deny" and "writes files with Edit or Write" in strict.message
    workspace = _decide(_phase(), "python3 -c 'print(1)'", {"shell": "strict"})
    assert workspace.decision == "deny" and "runs only plain test and read-only commands" in workspace.message
    assert workspace.remedy == {"setting": "device_runs.tool_defaults.shell", "value": "free"}


def test_a_read_only_phase_keeps_its_read_only_shell_and_the_stacks_runners_are_test_commands():
    read_only = _phase(capability_class="read_only", tools={"allow": ["run_test_suite"], "deny": []},
                       path_rules={"write": [], "create": [], "protect_confirmed_tests": False})
    assert _decide(read_only, "touch notes.txt").decision == "deny"
    assert _decide(read_only, "npm test") is None  # a stack's runner (stacks.json), not a fixed list in code
    assert ("npm", "test") in prefixes_of(None) and ("flutter", "test") in prefixes_of(None)
