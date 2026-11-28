"""One act, two engine shapes (backend/tests/conformance/scenarios.json): the launcher's hooks send the platform the
same request for a Claude Code and a Codex call and give each engine the same verdict."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from octryx_claude import (
    codex_hook_guard,
    codex_hook_input,
    hooks,
    plain_driver,
    post_tool_use_hook,
    pre_tool_use_hook,
    run_contract,
)
from octryx_claude.launch_sandbox import TEST_RUN_SHIM_ENV
from tests.hooks_support import KEY

from .conftest import BASE_URL

TABLE = json.loads((Path(__file__).resolve().parents[3] / "backend/tests/conformance/scenarios.json").read_text())
SCENARIOS = {scenario["id"]: scenario for scenario in TABLE["scenarios"]}
ACCEPTED = TABLE["accepted_differences"]
# tool_input fields one engine sends and the other does not, by the accepted difference that names them
ACCEPTED_FIELDS = {"patch_split_per_file": {"codex_patch", "content", "old_string", "new_string"},
                   "view_image_is_read": {"codex_tool"}}
CONTRACT = {"digest": "sha256:c1", "run": {"status": "running", "entry": "start", "current_node": {"id": "build"}}}
CLEARED_ENV = (codex_hook_input.ENGINE_ENV, codex_hook_guard.GUARDED_ENV, hooks.DEFER_STOP_ENV, "CLAUDE_PROJECT_DIR",
               "OCTRYX_WORK_ITEM", "OCTRYX_WORKFLOW_RUN", TEST_RUN_SHIM_ENV)


def _ids(same_request: bool | None = None) -> list:
    chosen = [key for key, scenario in SCENARIOS.items()
              if same_request is None or scenario["same_request"] is same_request]
    return [key for key in chosen]


@pytest.fixture
def run(state, tmp_path, monkeypatch, capsys):
    run_contract.remember(state, KEY, {"workflow_run": CONTRACT})
    cwd = tmp_path / "work"
    cwd.mkdir()

    def hook(runner, hook_input: dict, engine: str, answer: dict, **env: str) -> tuple[list, str]:
        for name in CLEARED_ENV:
            monkeypatch.delenv(name, raising=False)
        for name, value in {"OCTRYX_BASE_URL": BASE_URL, "OCTRYX_SESSION_KEY": KEY, "OCTRYX_WORKSPACE_ID": "ws-1",
                            **({codex_hook_input.ENGINE_ENV: codex_hook_input.CODEX} if engine == "codex" else {}),
                            **env}.items():
            monkeypatch.setenv(name, value)
        monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook_input).encode())))
        seen: list[tuple[str, dict]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.url.path.rsplit("/sessions/", 1)[-1], json.loads(request.content)))
            return httpx.Response(200, json=answer)

        capsys.readouterr()
        runner(state, httpx.Client(transport=httpx.MockTransport(handler)))
        return seen, capsys.readouterr().out

    hook.cwd = cwd
    return hook


def _files(cwd: Path, scenario: dict) -> None:
    added = {path for tool, path in codex_hook_input.patch_paths(scenario["codex"]["tool_input"].get("command", ""))
             if tool == "Write"}
    for relative in filter(None, [scenario["claude"]["tool_input"].get("file_path")]):
        (cwd / relative).parent.mkdir(parents=True, exist_ok=True)
        if relative not in added:
            (cwd / relative).write_text("VALUE = 0\n")


def _hook_input(engine: str, scenario: dict, cwd: Path, event: str = "PreToolUse") -> dict:
    shape = scenario[engine]
    tool_input = dict(shape["tool_input"])
    if engine == "claude" and "file_path" in tool_input:  # Claude Code sends absolute paths, Codex relative ones
        tool_input["file_path"] = str(cwd / tool_input["file_path"])
    return {"hook_event_name": event, "session_id": "s-1", "turn_id": "t-1", "tool_use_id": "call-1",
            "cwd": str(cwd), "tool_name": shape["tool_name"], "tool_input": tool_input}


def _answer(expect: dict) -> dict:
    if expect["decision"] == "deny":
        return {"decision": "deny", "state": "denied", "reason": expect["reason"], "message": "Not in this run."}
    return {"decision": expect["decision"], "state": "allowed"}


def _pre(run, engine: str, scenario: dict, answer: dict | None = None) -> tuple[list, str]:
    _files(run.cwd, scenario)
    guard = {codex_hook_guard.GUARDED_ENV: "1"} if engine == "codex" else {}  # as the device's Codex hook runs it
    return run(pre_tool_use_hook.run_pre_tool_use, _hook_input(engine, scenario, run.cwd), engine,
               answer or _answer(scenario["expect"]), **guard)


def _verdict(engine: str, out: str) -> tuple[str, str | None]:
    if engine == "codex":  # what Codex makes of it: the guard's exit code and reason
        code, _shown, reason = codex_hook_guard.answer(0, out.encode())
        return ("deny", reason) if code == codex_hook_guard.BLOCK else ("allow", None)
    specific = json.loads(out)["hookSpecificOutput"] if out else {}
    decision = specific.get("permissionDecision", "allow")
    return decision, None if decision == "allow" else specific.get("permissionDecisionReason")


def _comparable(body: dict) -> dict:
    ignored = set().union(*ACCEPTED_FIELDS.values())
    return {**body, "tool_input": {key: value for key, value in body["tool_input"].items() if key not in ignored}}


def test_the_fields_left_out_of_the_comparison_are_accepted_differences():
    assert set(ACCEPTED_FIELDS) <= set(ACCEPTED)


@pytest.mark.parametrize("key", _ids(same_request=True))
def test_both_shapes_send_the_same_tool_check(run, key):
    claude, _ = _pre(run, "claude", SCENARIOS[key])
    codex, _ = _pre(run, "codex", SCENARIOS[key])
    assert [path for path, _ in claude] == [path for path, _ in codex] == ["tool-check"]
    assert _comparable(codex[0][1]) == _comparable(claude[0][1])
    assert run_contract.FACTS_KEY in claude[0][1]


@pytest.mark.parametrize("key", _ids(same_request=False))
def test_shapes_that_differ_send_one_tool_check_each(run, key):
    for engine in ("claude", "codex"):
        seen, _ = _pre(run, engine, SCENARIOS[key])
        assert [path for path, _ in seen] == ["tool-check"]


@pytest.mark.parametrize("key", list(SCENARIOS))
def test_both_engines_get_the_platforms_verdict(run, key):
    expect = SCENARIOS[key]["expect"]
    verdicts = {engine: _verdict(engine, _pre(run, engine, SCENARIOS[key])[1]) for engine in ("claude", "codex")}
    assert verdicts["claude"] == verdicts["codex"]
    assert verdicts["claude"][0] == expect["decision"]
    if expect["decision"] == "deny":
        assert f"({expect['reason']}): Not in this run." in verdicts["claude"][1]


GIT_PUSH = {"claude": {"tool_name": "Bash", "tool_input": {"command": "git push"}},
            "codex": {"tool_name": "Bash", "tool_input": {"command": "git push"}}}


def test_ask_is_deny_on_codex(run):
    assert "ask_is_deny_on_codex" in ACCEPTED
    answer = {"decision": "ask", "state": "ask", "message": "Pushing needs a person."}
    assert _verdict("claude", _pre(run, "claude", GIT_PUSH, answer)[1]) == ("ask", "Pushing needs a person.")
    decision, reason = _verdict("codex", _pre(run, "codex", GIT_PUSH, answer)[1])
    assert decision == "deny" and reason == f"{codex_hook_input.ASK_DENIED} Pushing needs a person."


def test_updated_input_dropped_on_codex(run):
    assert "updated_input_dropped_on_codex" in ACCEPTED
    answer = {"decision": "allow", "state": "allowed", "updated_input": {"command": "git push --dry-run"}}
    claude = json.loads(_pre(run, "claude", GIT_PUSH, answer)[1])["hookSpecificOutput"]
    assert claude["updatedInput"] == {"command": "git push --dry-run"}
    out = _pre(run, "codex", GIT_PUSH, answer)[1]
    assert codex_hook_guard.answer(0, out.encode()) == (0, "", "")  # a plain allow: the call runs as written


def test_mcp_server_name(run):
    assert "mcp_server_name" in ACCEPTED
    seen, _ = _pre(run, "codex", SCENARIOS["platform_mcp_tool_name"])
    assert seen[0][1]["tool_name"] == "mcp__octryx-knowledge__knowledge_search"


def test_view_image_is_read(run):
    assert "view_image_is_read" in ACCEPTED
    seen, _ = _pre(run, "codex", SCENARIOS["an_image_is_read"])
    assert (seen[0][1]["tool_name"], seen[0][1]["tool_input"]) == (
        "Read", {"file_path": str(run.cwd / "docs/shot.png"), "codex_tool": "view_image"})


TWO_FILES = {"codex": {"tool_name": "apply_patch", "tool_input": {"command": (
    "*** Begin Patch\n*** Add File: src/new.py\n+x = 1\n*** Update File: src/app.py\n@@\n-VALUE = 0\n+VALUE = 1\n"
    "*** End Patch")}}, "claude": {"tool_input": {"file_path": "src/app.py"}}}


def test_patch_split_per_file(run):
    assert "patch_split_per_file" in ACCEPTED
    seen, _ = _pre(run, "codex", TWO_FILES, {"decision": "allow", "state": "allowed"})
    assert [(body["tool_name"], body["tool_input"]) for _, body in seen] == [
        ("Write", {"file_path": str(run.cwd / "src/new.py"), "codex_patch": True}),
        ("Edit", {"file_path": str(run.cwd / "src/app.py"), "codex_patch": True})]
    denied, out = _pre(run, "codex", TWO_FILES, _answer({"decision": "deny", "reason": "protected_path"}))
    assert len(denied) == 1 and _verdict("codex", out)[0] == "deny"  # the first denied file is the answer


@pytest.mark.parametrize("key", ["write_a_planned_source_file", "write_via_shell_patch"])
def test_post_tool_use_reports_the_same_tool_and_file_per_part(run, key):
    scenario = SCENARIOS[key]
    _files(run.cwd, scenario)
    reported = {}
    for engine in ("claude", "codex"):
        hook_input = {**_hook_input(engine, scenario, run.cwd, "PostToolUse"), "tool_response": "Success."}
        seen, _ = run(post_tool_use_hook.run_post_tool_use, hook_input, engine, {"state": "recorded"})
        reported[engine] = [(body["tool_name"], body["tool_input"]["file_path"]) for path, body in seen
                            if path == "tool-executed"]
    assert reported["codex"] == reported["claude"] and len(reported["claude"]) == 1


STOP = {"hook_event_name": "Stop", "session_id": "s-1", "turn_id": "t-1", "stop_hook_active": False}


def _stop(run, engine: str, **env: str) -> tuple[list, str]:
    return run(hooks.run_stop, {**STOP, "cwd": str(run.cwd)}, engine, {"state": "passed"},
               CLAUDE_PROJECT_DIR=str(run.cwd), **env)


def _verification(seen: list) -> dict:
    bodies = [body for path, body in seen if path == "verification"]
    assert len(bodies) == 1
    return bodies[0]


def test_stop_sends_the_same_verification_body_for_both_engines(run):
    claude = _verification(_stop(run, "claude")[0])
    assert _verification(_stop(run, "codex")[0]) == claude
    assert {key: claude[key] for key in ("hook_event_name", "session_id", "turn_id")} == {
        "hook_event_name": "Stop", "session_id": "s-1", "turn_id": "t-1"}
    assert set(claude[run_contract.FACTS_KEY]) >= {"node_id", "entry", "checked_files"}


def test_stop_deferred_on_codex(run, state, monkeypatch):
    assert "stop_deferred_on_codex" in ACCEPTED
    claude = _verification(_stop(run, "claude")[0])
    seen, out = _stop(run, "codex", **{hooks.DEFER_STOP_ENV: "1"})
    prepared = SimpleNamespace(session_key=KEY, env={"OCTRYX_CLAUDE_HOME": str(state.root),
                                                     hooks.DEFER_STOP_ENV: "1"}, extra={})
    assert seen == [] and out == ""
    assert plain_driver.deferred_stop_input(prepared) == {**STOP, "cwd": str(run.cwd)}
    replayed: list = []

    # The replay's own hook process, run in this process: the env the driver gives it, the input it saved.
    def stop_hook(command, data, cwd, env):
        assert command[-2:] == ["hook", "stop"] and env[hooks.DEFER_STOP_ENV] == "0"
        replayed.extend(_stop_with_input(run, data, env))
        return None, True

    monkeypatch.setattr(plain_driver, "_run_stop_hook", stop_hook)
    assert plain_driver.judged_stop(prepared, str(run.cwd), shim="octryx-claude") == (None, True)
    assert _verification(replayed) == claude
    assert plain_driver.deferred_stop_input(prepared) is None


def _stop_with_input(run, data: bytes, env: dict) -> list:
    saved = json.loads(data)
    return run(hooks.run_stop, saved, "codex", {"state": "passed"}, CLAUDE_PROJECT_DIR=env["CLAUDE_PROJECT_DIR"],
               **{hooks.DEFER_STOP_ENV: env[hooks.DEFER_STOP_ENV]})[0]
