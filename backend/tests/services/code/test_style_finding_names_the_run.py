"""The platform's style finding names the command and the folder it ran, so the agent runs exactly that (otherwise
the agent's own run can disagree with the platform's)."""

from app.services.code_style.schema import normalize_profile
from app.services.code_style.schema_values import CodeStyleError
from app.services.code_style.tool_check import tool_findings


def test_a_failed_tool_names_what_the_platform_ran_and_where():
    [finding] = tool_findings([{"language": "python", "kind": "linter", "tool": "ruff", "config": "platform",
                                "state": "failed", "folder": "e2e/python",
                                "command": "ruff check --select E,F,I,B", "output": "I001 Import block"}])
    assert "(ran `ruff check --select E,F,I,B` in e2e/python/)" in finding.text()


def test_a_tool_may_say_it_runs_only_outside_the_sandbox():
    profile = normalize_profile({"languages": {"dart": {"formatter": {"command": "dart format {files}",
                                                                      "outside_sandbox": True}}}})
    assert profile["languages"]["dart"]["formatter"]["outside_sandbox"] is True
    try:
        normalize_profile({"languages": {"dart": {"formatter": {"command": "dart format", "outside_sandbox": "yes"}}}})
    except CodeStyleError:
        return
    raise AssertionError("a non-boolean outside_sandbox must be refused")
