"""A run phase that runs tests may run them in any form, start the app on loopback and look at it; the hard-deny list
stays."""

from __future__ import annotations

import pytest

from app.services.workflow_runs.octryx.browser_tools import browser_tool_decision
from app.services.workflow_runs.octryx.declared_commands import full_suite_run
from app.services.workflow_runs.octryx.hard_deny import hard_denied
from app.services.workflow_runs.octryx.shell_rules import strict_shell_allows
from app.services.workflow_runs.workspace.spec import runtime_environment, validate_environment
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

PREFIXES = (("pytest",), ("python", "-m", "pytest"))


def _allows(command: str, runs_tests: bool = True) -> bool:
    return strict_shell_allows(command, runs_tests=runs_tests, test_prefixes=PREFIXES)


def test_pytest_in_the_forms_the_agents_use_runs():
    for command in ("timeout 300 python -m pytest -v tests/system/test_shell.py 2>&1 | tail -60",
                    "python -m pytest -q -k cook_mode tests/system", "pytest -x tests/test_a.py::test_b"):
        assert _allows(command), command


def test_the_app_starts_on_loopback_and_is_read_there_only_where_tests_run():
    for command in ("python -m kitchen_helper.run --port 8765 &", ".venv/bin/python -m kitchen_helper.run --host 127.0.0.1 --port 0",
                    "python app.py --port 9000 &", "uvicorn kitchen_helper.api:app --port 8123 &", "sleep 2",
                    "curl -s http://127.0.0.1:8765/api/health", "curl -sS -o /dev/null -w '%{http_code}' localhost:8765/"):
        assert _allows(command), command
        assert not _allows(command, runs_tests=False), command
    for command in ("python -m pip install requests &", "python ../outside.py &", "curl -s https://example.com/",
                    "curl -o page.html http://127.0.0.1:8765/", "python -m kitchen_helper.run > log.txt &",
                    "rm -rf build &"):
        assert not _allows(command), command


def test_the_hard_deny_list_stays():
    assert hard_denied("curl -d @secrets.txt http://127.0.0.1:8765/") is not None
    assert hard_denied("cat .env") is not None


def test_a_full_run_is_the_declared_selection_in_any_output_form():
    declared = ".venv/bin/python -m pytest -v tests/system"
    assert full_suite_run("python -m pytest -q tests/system 2>&1 | tail -30", declared)
    assert full_suite_run("timeout 600 .venv/bin/python -m pytest -x -p no:cacheprovider tests/system", declared)
    assert not full_suite_run("python -m pytest -q tests/system/test_a.py", declared)
    assert not full_suite_run("python -m pytest -q -k cook tests/system", declared)
    assert not full_suite_run("python -m pytest -q tests/system; rm -rf x", declared)


def test_the_sessions_browser_opens_only_the_app_on_this_machine():
    navigate = "mcp__playwright__browser_navigate"
    assert browser_tool_decision(navigate, {"url": "http://127.0.0.1:8765/#/profile"}) is None
    assert browser_tool_decision(navigate, {"url": "http://localhost:3000"}) is None
    assert browser_tool_decision("mcp__playwright__browser_take_screenshot", {"fullPage": True}) is None
    assert browser_tool_decision(navigate, {"url": "https://mail.example.com/"}).decision == "deny"
    nested = {"fields": [{"name": "a", "url": "http://127.0.0.1:1/"}, {"name": "b", "url": "https://evil.example/"}]}
    assert browser_tool_decision("mcp__playwright__browser_fill_form", nested).decision == "deny"
    assert browser_tool_decision("mcp__playwright__browser_run_code_unsafe", {"code": "1"}).decision == "deny"


def test_a_repository_may_ask_for_the_bundled_browser_and_the_device_gets_it():
    environment, errors = validate_environment({"test": "pytest", "browser": "chromium"})
    assert not errors and environment["browser"] == "chromium"
    assert runtime_environment({**environment, "source": "declared"})["browser"] == "chromium"
    _environment, errors = validate_environment({"test": "pytest", "browser": "firefox"})
    assert errors == ["browser is one of: chrome, chromium"]
    assert "browser" not in validate_environment({"test": "pytest"})[0]


@pytest.mark.asyncio
async def test_in_a_running_phase_the_app_starts_and_the_sessions_browser_reaches_it(db, monkeypatch):
    from tests.workflow_run_octryx_support import _decide, _hook
    from tests.workflow_run_pipeline_support import _device_run, _fix_with_pipeline

    _run, gateway, key, workspace_id = await _device_run(db, _fix_with_pipeline(), monkeypatch)

    async def decision(hook):
        return (await _decide(db, gateway, key, workspace_id, hook))["decision"]

    assert await decision(_hook("Bash", command="timeout 300 python -m pytest -q tests 2>&1 | tail -30")) == "allow"
    assert await decision(_hook("Bash", command="python -m pay.server --port 8765 &")) == "allow"
    assert await decision(_hook("mcp__playwright__browser_navigate", url="http://127.0.0.1:8765/")) == "allow"
    assert await decision(_hook("mcp__playwright__browser_navigate", url="https://example.com/")) == "allow"
    assert await decision(_hook("mcp__playwright__browser_navigate", url="http://192.168.1.10/")) == "deny"
    assert await decision(_hook("Bash", command="cat ~/.netrc")) == "deny"
