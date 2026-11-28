from __future__ import annotations

import io
import json
import os

import httpx

from octryx_claude import post_tool_use_hook, pre_tool_use_hook, run_contract

from .conftest import BASE_URL

KEY = ("0b6c" + "4a52-3b1e-4c1b-9f55-1d1c1b1a1f10")
DECLARED = "python -m pytest -v tests/ --junitxml=test-reports/report.xml"
JUNIT = ('<testsuite><testcase classname="tests.test_textkit" name="test_slug"><failure message="x"/></testcase>'
         "</testsuite>")


def _contract(source: str = "declared") -> dict:
    return {"digest": "sha256:1", "run": {"id": "r1"}, "phase": {"title": "Tests first"},
            "preparation": {"environment": {"source": source, "test": DECLARED}}}


def _hook(event: str, root, command: str = DECLARED) -> dict:
    return {"hook_event_name": event, "tool_name": "Bash", "tool_use_id": "toolu_j1", "cwd": str(root),
            "tool_input": {"command": command}}


def _call(state, monkeypatch, runner, hook_input) -> list[httpx.Request]:
    monkeypatch.setenv("OCTRYX_BASE_URL", BASE_URL)
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook_input).encode())))
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"state": "recorded", "decision": "allow"})

    assert runner(state, httpx.Client(transport=httpx.MockTransport(handler))) == 0
    return seen


def _run_declared(state, monkeypatch, root, *, write: bool, command: str = DECLARED) -> dict:
    _call(state, monkeypatch, pre_tool_use_hook.run_pre_tool_use, _hook("PreToolUse", root, command))
    if write:
        report = root / "test-reports" / "report.xml"
        report.parent.mkdir(exist_ok=True)
        report.write_text(JUNIT)
        os.utime(report, ns=(report.stat().st_mtime_ns + 10**9,) * 2)  # a later write, whatever the clock's grain
    [sent] = _call(state, monkeypatch, post_tool_use_hook.run_post_tool_use, _hook("PostToolUseFailure", root, command))
    return json.loads(sent.content)


def test_the_report_the_declared_command_wrote_is_attached(state, monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    run_contract.remember(state, KEY, {"workflow_run": _contract()})
    body = _run_declared(state, monkeypatch, tmp_path, write=True)
    assert body[run_contract.FACTS_KEY]["test_report"] == {"format": "junit", "path": "test-reports/report.xml",
                                                            "junit_xml": JUNIT}


def test_a_stale_report_a_changed_command_or_a_proposal_attaches_nothing(state, monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    run_contract.remember(state, KEY, {"workflow_run": _contract()})
    _run_declared(state, monkeypatch, tmp_path, write=True)
    stale = _run_declared(state, monkeypatch, tmp_path, write=False)  # the runner did not write it this time
    assert run_contract.FACTS_KEY not in stale
    changed = _run_declared(state, monkeypatch, tmp_path, write=True, command=DECLARED + " -x")
    assert run_contract.FACTS_KEY not in changed
    run_contract.remember(state, KEY, {"workflow_run": _contract("ci_derived")})
    assert run_contract.FACTS_KEY not in _run_declared(state, monkeypatch, tmp_path, write=True)


def test_a_report_outside_the_repository_is_never_read(state, monkeypatch, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    outside = "python -m pytest -v tests/ --junitxml=../report.xml"
    contract = _contract()
    contract["preparation"]["environment"]["test"] = outside
    run_contract.remember(state, KEY, {"workflow_run": contract})
    _call(state, monkeypatch, pre_tool_use_hook.run_pre_tool_use, _hook("PreToolUse", root, outside))
    (tmp_path / "report.xml").write_text(JUNIT)
    [sent] = _call(state, monkeypatch, post_tool_use_hook.run_post_tool_use, _hook("PostToolUse", root, outside))
    assert run_contract.FACTS_KEY not in json.loads(sent.content)


def test_the_report_carries_the_test_files_its_classnames_name(state, monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_textkit.py").write_text("def test_slug():\n    assert False\n")
    run_contract.remember(state, KEY, {"workflow_run": _contract()})
    body = _run_declared(state, monkeypatch, tmp_path, write=True)
    assert body[run_contract.FACTS_KEY]["test_report"]["files"] == ["tests/test_textkit.py"]


def test_hint_files_are_bounded_to_existing_files_inside_the_repository(tmp_path):
    from octryx_claude.test_report import hint_files

    root = tmp_path / "repo"
    (root / "tests" / "unit").mkdir(parents=True)
    (root / "tests" / "unit" / "test_a.py").write_text("")
    (tmp_path / "evil.py").write_text("")
    xml = ('<testsuite><testcase classname="tests.unit.test_a.TestA.TestInner" name="test_x[1]"/>'
           '<testcase classname="" name="tests.unit.test_a"><error message="collection failure"/></testcase>'
           '<testcase classname="..evil" name="x"/><testcase classname="missing.mod" name="t"/></testsuite>')
    assert hint_files(xml, root, root) == ["tests/unit/test_a.py"]
