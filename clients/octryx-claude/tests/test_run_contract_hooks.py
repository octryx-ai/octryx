"""The run contract in hooks, prompts and banners: digests, pending decisions, phases and the read-only assistant."""

from __future__ import annotations

import hashlib
import io
import json

import httpx

from octryx_claude import contract_notices, hooks, launch, pre_tool_use_hook, run_contract, session_hooks
from tests.run_contract_support import RUN, _contract

from .conftest import BASE_URL

KEY = ("0b6c" + "4a52-3b1e-4c1b-9f55-1d1c1b1a1f10")


def _env(monkeypatch, hook_input: dict, project_dir) -> None:
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook_input).encode())))
    monkeypatch.setenv("OCTRYX_BASE_URL", BASE_URL)
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))


def test_the_contract_is_remembered_shown_once_and_a_pending_decision_points_to_the_platform(state):
    assert run_contract.remember(state, KEY, {"state": "allowed"}) is None
    contract = run_contract.remember(state, KEY, {"workflow_run": _contract()})
    assert run_contract.current(state, KEY) == contract
    first = contract_notices.changed_notice(state, KEY, contract)
    assert "phase 'Minimal fix' (change); Fix ↔ test 2/4" in first
    assert contract_notices.changed_notice(state, KEY, contract) == ""  # shown once
    assert run_contract.pending_notice(state, KEY) == ""

    paused = _contract(digest="sha256:two", phase=None,
                       paused={"reason": "loop_limit", "decide_in": "https://octryx.example.test/chat/s1"})
    run_contract.remember(state, KEY, {"workflow_run": paused})
    assert run_contract.pending_notice(state, KEY) == (
        "Workflow run bug-fix-reproduction is paused: loop_limit. Decide in Octryx: "
        "https://octryx.example.test/chat/s1.")


def test_pre_tool_use_reports_the_digests_and_remembers_the_answer(state, tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    (project / "tests" / "test_totals.py").write_text("x")
    run_contract.remember(state, KEY, {"workflow_run": _contract()})
    hook_input = {"hook_event_name": "PreToolUse", "tool_name": "Edit",
                  "tool_input": {"file_path": str(project / "tests" / "test_totals.py")}}
    _env(monkeypatch, hook_input, project)
    seen: list[dict] = []
    answer_contract = _contract(digest="sha256:three")

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"decision": "deny", "state": "denied", "reason": "confirmed_test_protected",
                                         "message": "a confirmed test", "workflow_run": answer_contract})

    assert pre_tool_use_hook.run_pre_tool_use(state, httpx.Client(transport=httpx.MockTransport(handler))) == 0
    digest = "sha256:" + hashlib.sha256(b"x").hexdigest()
    assert seen[0][run_contract.FACTS_KEY] == {
        "node_id": None, "entry": None, "confirmed_test_digests": {"tests/test_totals.py": digest},
        "confirmed_test_texts": {"tests/test_totals.py": "x"},
        "checked_files": ["tests/test_totals.py"], "resolved_path": "tests/test_totals.py", "target_exists": True,
        "shadows_installed": False}
    assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert run_contract.current(state, KEY)["digest"] == "sha256:three"


def test_the_prompt_hook_tells_the_model_the_phase_and_the_user_the_pending_decision(state, tmp_path, monkeypatch,
                                                                                      capsys):
    waiting = _contract(waiting={"kind": "awaiting_confirmation", "question": "Confirm the reproduction",
                                 "decide_in": "https://octryx.example.test/chat/s1"})
    run_contract.remember(state, KEY, {"workflow_run": waiting})
    _env(monkeypatch, {"hook_event_name": "UserPromptSubmit", "prompt": "go on"}, tmp_path)
    prompts: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:  # the platform answers with the current contract
        prompts.append({"path": request.url.path, **json.loads(request.content)})
        return httpx.Response(200, json={"state": "ok", "workflow_run": waiting})

    assert session_hooks.run_user_prompt_submit(state, httpx.Client(transport=httpx.MockTransport(handler))) == 0
    output = json.loads(capsys.readouterr().out)
    assert "waits: Confirm the reproduction" in output["hookSpecificOutput"]["additionalContext"]
    assert "https://octryx.example.test/chat/s1" in output["systemMessage"]
    assert prompts == [{"path": "/api/v1/agent-gateway/sessions/prompt", "prompt": "go on"}]

    # A decision taken in the platform meanwhile: the next prompt already sees the new phase.
    moved = _contract(digest="sha256:moved")
    _env(monkeypatch, {"hook_event_name": "UserPromptSubmit", "prompt": "next"}, tmp_path)
    assert session_hooks.run_user_prompt_submit(state, httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"state": "ok", "workflow_run": moved})))) == 0
    output = json.loads(capsys.readouterr().out)
    assert "phase 'Minimal fix'" in output["hookSpecificOutput"]["additionalContext"]
    assert "systemMessage" not in output


def test_the_banner_shows_workflow_phase_loop_and_where_the_decision_is_taken():
    lines = contract_notices.banner(_contract(run={**_contract()["run"], "workflow_version": 3, "ticket_key": "PAY-1"}))
    assert lines == ["workflow run bug-fix-reproduction v3 (running) | PAY-1", "phase: Minimal fix (change)",
                     "loop: Fix ↔ test 2/4"]
    waiting = contract_notices.banner(_contract(
        phase=None, loop=[], link="https://octryx.example.test/chat/s1",
        waiting={"kind": "awaiting_confirmation", "question": "Confirm the test contract"},
        decision={"kind": "user_confirmation", "in_terminal": True, "actions": ["confirm", "change", "stop"]}))
    assert waiting[1] == "waiting for: Confirm the test contract"
    assert waiting[2].startswith("decide here (confirm, change, stop") and "octryx.example.test/chat/s1" in waiting[2]
    four_eyes = contract_notices.banner(_contract(phase=None, loop=[], link="https://octryx.example.test/chat/s1",
                                              waiting={"kind": "awaiting_approval", "title": "Deploy approval"},
                                              decision={"kind": "approval", "in_terminal": False}))
    assert four_eyes[2] == "decide in Octryx: https://octryx.example.test/chat/s1"


def test_a_work_item_session_gets_the_first_prompts_proposal_and_a_plain_session_asks_nothing(state, tmp_path,
                                                                                            monkeypatch, capsys):
    proposal = {"state": "proposed", "workflow_key": "bug-fix-reproduction", "workflow_title": "Bug fix",
                "reason": "a defect with steps", "phased": True,
                "next": {"tool": "workflow_select", "arguments": {"workflow_key": "bug-fix-reproduction",
                                                                  "work_item": "PAY-1"}}}
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("X-Octryx-Work-Item", ""))
        return httpx.Response(200, json={"state": "ok", "workflow_proposal": proposal})

    _env(monkeypatch, {"hook_event_name": "UserPromptSubmit", "prompt": "fix it"}, tmp_path)
    monkeypatch.setenv("OCTRYX_WORK_ITEM", "PAY-1")
    assert session_hooks.run_user_prompt_submit(state, httpx.Client(transport=httpx.MockTransport(handler))) == 0
    output = json.loads(capsys.readouterr().out)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "phased workflow run 'bug-fix-reproduction'" in context and "Never start it without asking" in context
    assert "work_item='PAY-1'" in context and output["systemMessage"].startswith("Proposed workflow: 'Bug fix'")
    assert seen == ["PAY-1"]

    monkeypatch.delenv("OCTRYX_WORK_ITEM")
    _env(monkeypatch, {"hook_event_name": "UserPromptSubmit", "prompt": "hi"}, tmp_path)
    assert session_hooks.run_user_prompt_submit(state, httpx.Client(transport=httpx.MockTransport(handler))) == 0
    assert seen == ["PAY-1"]  # no Work item and no run: nothing is asked


def test_the_launcher_shows_the_run_banner_from_the_registration_answer(state, capsys):
    from octryx_claude import cli_session
    from octryx_claude.platform import SessionContext

    context = SessionContext(BASE_URL, KEY, "ws-1", "PAY-1")
    cli_session.show_run(state, context, {"state": "registered", "workflow_run": _contract()})
    assert "octryx-claude: phase: Minimal fix (change)" in capsys.readouterr().err
    assert run_contract.current(state, KEY)["digest"] == "sha256:one"
    assert contract_notices.changed_notice(state, KEY, run_contract.current(state, KEY)) == ""  # not again at a hook
    cli_session.show_run(state, context, {"state": "registered",
                                         "workflow_run_attach": {"state": "denied", "reason": "run_read_only"}})
    assert "work item run not attached (run_read_only)" in capsys.readouterr().err


def test_a_device_job_carries_its_run_to_the_model_gateway_only_as_a_header():
    headers = launch.custom_headers(KEY, "ws-1", "", workflow_run=RUN)
    assert f"X-Octryx-Workflow-Run: {RUN}" in headers.splitlines()
    assert "Workflow-Run" not in launch.custom_headers(KEY, "ws-1", "")


def test_a_run_waiting_for_its_terminals_preparation_says_how_to_prepare():
    from octryx_claude.contract_notices import summary

    contract = {"run": {"workflow_key": "feature-delivery-tdd", "status": "running"}, "phase": None,
                "preparation": {"state": "pending", "runtime": "terminal", "branch": "feature/BRD-8"}}
    line = summary(contract)
    assert "feature/BRD-8" in line and "start octryx-claude again in the repository folder" in line


def test_the_phase_agent_reaches_the_model_once_per_digest(state):
    # The contract's phase agent and its instructions, shown to the model once.
    agent = {"key": "engineer", "name": "Engineer", "version": 2, "instructions": "Tests are the contract.",
             "digest": "sha256:a1"}
    contract = _contract(phase={**_contract()["phase"], "agent": agent})
    first = contract_notices.agent_notice(state, KEY, contract)
    assert first.startswith("You work as the Octryx Engineer agent (v2) in this workflow phase.")
    assert "Tests are the contract." in first
    assert contract_notices.agent_notice(state, KEY, contract) == ""
    changed = _contract(phase={**_contract()["phase"], "agent": {**agent, "digest": "sha256:a2"}})
    assert contract_notices.agent_notice(state, KEY, changed)


def test_outside_a_run_the_registration_agent_is_the_read_only_assistant(state):
    contract_notices.remember_platform_agent(state, KEY, {"platform_agent": {
        "key": "assistant", "name": "Assistant", "version": 1, "instructions": "Evidence first.",
        "digest": "sha256:b1", "capability_class": "read_only"}})
    notice = contract_notices.agent_notice(state, KEY, None)
    assert "Assistant agent (v1)" in notice and "read-only" in notice and "Evidence first." in notice
    assert contract_notices.agent_notice(state, KEY, None) == ""
    # A run contract without an agent (a version before phase agents) shows nothing.
    assert contract_notices.agent_notice(state, KEY, _contract()) == ""


def test_a_session_whose_read_only_assistant_is_lifted_is_told_once(state):
    # a resumed session kept "read-only" in its history; the model is told once it no longer applies
    contract_notices.remember_platform_agent(state, KEY, {"platform_agent": {
        "digest": "d1", "name": "Assistant", "instructions": "You never change code."}})
    assert "read-only" in contract_notices.agent_notice(state, KEY, None)
    contract_notices.remember_platform_agent(state, KEY, {})  # the next registration: no read-only Assistant
    lifted = contract_notices.agent_notice(state, KEY, None)
    assert "no longer read-only" in lifted and "permission mode" in lifted
    assert contract_notices.agent_notice(state, KEY, None) == ""  # once
    contract_notices.remember_platform_agent(state, KEY, {})  # nothing kept: nothing to say
    assert contract_notices.agent_notice(state, KEY, None) == ""


def test_a_stop_that_passes_into_the_next_phase_goes_on_in_this_turn_with_its_compact_contract(state, tmp_path,
                                                                                              monkeypatch, capsys):
    """(size class ``phase_change: same_turn``): the launcher says it can go on, and a
    ``next_phase`` answer blocks the Stop with the next phase's prompt and its compact contract, without counting
    as a refused Stop."""
    run_contract.remember(state, KEY, {"workflow_run": _contract()})
    _env(monkeypatch, {"hook_event_name": "Stop", "stop_hook_active": False}, tmp_path)
    nxt = {**_contract(digest="sha256:next"), "detail_paths": ["phase.code_style"]}
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sessions/verification"):
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"state": "next_phase", "workflow_run": nxt,
                                             "detail": "The run moves on to phase 'Minimal fix'."})
        return httpx.Response(200, json={"state": "ok"})

    assert hooks.run_stop(state, httpx.Client(transport=httpx.MockTransport(handler))) == 0
    output = json.loads(capsys.readouterr().out)
    assert seen[0]["capabilities"] == ["next_phase"]
    assert output["decision"] == "block" and output["reason"].startswith("The run moves on to phase 'Minimal fix'.")
    assert "Your run contract for this phase (compact" in output["reason"]
    counters = json.loads((state.session_dir(KEY) / "stop_blocks.json").read_text())
    assert set(counters.values()) == {0}
