"""Codex code mode: inner calls of one ``exec`` count as gateway evidence.

A hook-reported inner call (``exec-<uuid>``) counts when the same tool with the same literal arguments appears in an
``exec`` input the gateway recorded for the same session, after the model asked for that exec, each occurrence once.
Dynamic arguments never count; the Stop answer then tells the model to use a literal command string. A Claude Code
session is never touched.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from app.models import Session, ToolCall
from app.services.agent_gateway.codex_exec_evidence import (
    LITERAL_HINT,
    codex_exec_evidence,
    exec_call_record,
    match_exec_calls,
    with_literal_hint,
)
from app.services.agent_gateway.codex_exec_keys import EXEC_CALL_KEY
from app.services.agent_gateway.codex_exec_parser import exec_occurrences
from app.services.agent_gateway.read_evidence import native_read_use
from app.services.workflow_runs.octryx.stop_evidence import phase_evidence
from tests.agent_gateway.codex_exec_evidence_support import OK_EXCERPT, _counted
from tests.workflow_run_runtime_evidence_support import ROOT

T0 = datetime(2026, 11, 15, 10, 35, 0)


SESSION = "codex-session"


def _previous_write(at: datetime, session_id: str = SESSION) -> ToolCall:
    """The gateway write that ended the response emitting the next exec."""
    return ToolCall(session_id=session_id, tool_name="exec", request_id=f"call_{uuid.uuid4().hex}",
                    parameters={"source": "model_gateway", "block_index": 0, "input": {"input": "text(1)"}},
                    result={"is_error": False, "excerpt": "Script completed"}, status="success", created_at=at)


def _exec(script: str, at: datetime, *, session_id: str = SESSION, excerpt: str = OK_EXCERPT) -> ToolCall:
    call_id = f"call_{uuid.uuid4().hex}"
    return ToolCall(session_id=session_id, tool_name="exec", request_id=call_id,
                    parameters={"source": "model_gateway", "tool_use_id": call_id, "block_index": 0,
                                "input": {"input": script}},
                    result={"is_error": False, "excerpt": excerpt}, status="success", created_at=at)


def _hook(tool: str, tool_input: dict, at: datetime, *, session_id: str = SESSION, outcome: str = "succeeded",
          read: dict | None = None) -> ToolCall:
    tool_use_id = f"exec-{uuid.uuid4()}"
    parameters = {"source": "model_gateway", "tool_use_id": tool_use_id,
                  "executed": {"outcome": outcome, "source": "client_hook"},
                  EXEC_CALL_KEY: exec_call_record(tool, {"tool_input": tool_input, "cwd": ROOT})}
    if read is not None:
        parameters["read_target"] = read
    return ToolCall(session_id=session_id, tool_name=tool, request_id=tool_use_id, parameters=parameters,
                    result=None, status="requested", created_at=at)


def _readme_read(at: datetime, **kwargs) -> ToolCall:
    return _hook("Bash", {"command": "/bin/zsh -lc 'cat README.md'"}, at, read={
        "tool": "Bash", "read_tool": "read_workspace_file", "in_root": True, "path": "README.md"}, **kwargs)


# --- parsing --------------------------------------------------------------------------------------------------------


def test_only_literal_calls_are_recognised():
    found = exec_occurrences(
        'text(await tools.exec_command({cmd:"cat README.md"})); '
        'const x = "a.py"; await tools.exec_command({cmd:`cat ${x}`}); '
        'await tools.exec_command({cmd:"cat " + x}); await tools.exec_command({cmd}); '
        'text("tools.exec_command({cmd:\\"ls\\"})"); '  # inside a string: no call
        'await tools.exec_command({cmd:`ls -a`, "max_output_tokens":2000})')
    assert [(item.name, item.literal, item.args) for item in found] == [
        ("exec_command", True, {"cmd": "cat README.md"}),
        ("exec_command", False, None),
        ("exec_command", False, None),
        ("exec_command", False, None),
        ("exec_command", True, {"cmd": "ls -a", "max_output_tokens": 2000}),
    ]


# --- positive ---------------------------------------------------------------------------------------------------------


def test_cat_readme_inside_exec_is_read_evidence():
    rows = [_previous_write(T0), _readme_read(T0 + timedelta(seconds=2)),
            _exec('text(await tools.exec_command({cmd:"cat README.md"}))', T0 + timedelta(seconds=6))]
    matched = match_exec_calls(rows)
    assert len(matched.matched) == 1 and not matched.unmatched
    use = native_read_use(_counted(matched.rows)[0])
    assert use.name == "read_workspace_file" and use.succeeded is True
    assert native_read_use(rows[1]).succeeded is False  # the stored row itself is unchanged


def test_promise_all_settled_with_three_literal_calls_matches_each_once():
    script = ('const r=await Promise.allSettled([tools.exec_command({cmd:"cat README.md"}),'
              'tools.exec_command({cmd:\'ls -a\'}),tools.mcp__octryx_knowledge__knowledge_search('
              '{query:"OCX-36 spec",limit:5})]);r.forEach(text);')
    at = T0 + timedelta(seconds=2)
    hooks = [_readme_read(at), _hook("Bash", {"command": "ls -a"}, at, read={
        "tool": "Bash", "read_tool": "list_workspace_directory", "in_root": True, "path": "."}),
        _hook("mcp__octryx-knowledge__knowledge_search", {"query": "OCX-36 spec", "limit": 5}, at)]
    exec_row = _exec(script, T0 + timedelta(seconds=8))
    matched = match_exec_calls([_previous_write(T0), *hooks, exec_row])
    counted = _counted(matched.rows)
    assert len(counted) == 3 and not matched.unmatched
    assert sorted(row.parameters["exec_match"]["occurrence"] for row in counted) == [0, 1, 2]
    evidence = phase_evidence(matched.rows, since=None, test_prefixes=(("pytest",),))
    names = {use.name for use in evidence.tools if use.succeeded}
    assert {"read_workspace_file", "list_workspace_directory", "knowledge_search"} <= names


def test_a_patch_and_a_test_run_inside_exec_count_as_change_and_test():
    patch = "*** Begin Patch\\n*** Add File: docs/SPEC.md\\n+hi\\n*** End Patch"
    at = T0 + timedelta(seconds=2)
    write = _hook("Write", {"file_path": f"{ROOT}/docs/SPEC.md", "codex_patch": True}, at)
    test = _hook("Bash", {"command": "pytest -q"}, at + timedelta(seconds=3))
    rows = [_previous_write(T0), write, _exec(f'await tools.apply_patch("{patch}")', T0 + timedelta(seconds=4)),
            test, _exec('text(await tools.exec_command({cmd:"pytest -q"}))', T0 + timedelta(seconds=9),
                        excerpt=OK_EXCERPT.replace('"output":"..."', '"output":"3 passed in 0.1s"'))]
    matched = match_exec_calls(rows)
    assert len(matched.matched) == 2
    evidence = phase_evidence(matched.rows, since=None, test_prefixes=(("pytest",),))
    assert [use.name for use in evidence.tools] == ["edit_workspace_file", "run_test_suite"]
    assert all(use.succeeded for use in evidence.tools) and evidence.tools[1].result["all_green"] is True


def test_a_test_whose_exec_reports_a_non_zero_exit_is_not_green():
    rows = [_previous_write(T0), _hook("Bash", {"command": "pytest -q"}, T0 + timedelta(seconds=2)),
            _exec('text(await tools.exec_command({cmd:"pytest -q"}))', T0 + timedelta(seconds=5),
                  excerpt=OK_EXCERPT.replace('"exit_code":0', '"exit_code":1').replace(
                      '"output":"..."', '"output":"1 failed, 2 passed in 0.1s"'))]
    evidence = phase_evidence(match_exec_calls(rows).rows, since=None, test_prefixes=(("pytest",),))
    assert evidence.tools[-1].name == "run_test_suite" and evidence.tools[-1].result["all_green"] is False


# --- negative ---------------------------------------------------------------------------------------------------------


def test_interpolation_is_no_evidence_and_earns_the_hint():
    rows = [_previous_write(T0), _readme_read(T0 + timedelta(seconds=2)),
            _exec('const f="README.md"; text(await tools.exec_command({cmd:`cat ${f}`}))', T0 + timedelta(seconds=5))]
    matched = match_exec_calls(rows)
    assert not matched.matched and len(matched.unmatched) == 1
    blocked = {"state": "blocked", "detail": "Phase 'Draft' is not done: read the code."}
    assert with_literal_hint(blocked, matched)["detail"].endswith(LITERAL_HINT)
    assert with_literal_hint({"state": "passed", "detail": ""}, matched)["detail"] == ""


def test_a_command_not_in_the_exec_input_is_no_evidence():
    rows = [_previous_write(T0), _readme_read(T0 + timedelta(seconds=2)),
            _exec('text(await tools.exec_command({cmd:"cat pyproject.toml"}))', T0 + timedelta(seconds=5))]
    assert not match_exec_calls(rows).matched


def test_a_hook_report_before_the_model_asked_for_the_exec_is_no_evidence():
    # The report predates the gateway write that ended the response emitting the exec (beyond the skew).
    rows = [_readme_read(T0), _previous_write(T0 + timedelta(seconds=30)),
            _exec('text(await tools.exec_command({cmd:"cat README.md"}))', T0 + timedelta(seconds=40))]
    assert not match_exec_calls(rows).matched


def test_one_occurrence_is_consumed_only_once():
    at = T0 + timedelta(seconds=2)
    rows = [_previous_write(T0), _readme_read(at), _readme_read(at + timedelta(seconds=1)),
            _exec('text(await tools.exec_command({cmd:"cat README.md"}))', T0 + timedelta(seconds=6))]
    matched = match_exec_calls(rows)
    assert len(matched.matched) == 1 and len(matched.unmatched) == 1


def test_an_exec_of_another_session_is_no_evidence():
    rows = [_previous_write(T0), _readme_read(T0 + timedelta(seconds=2)),
            _exec('text(await tools.exec_command({cmd:"cat README.md"}))', T0 + timedelta(seconds=6),
                  session_id="other-session")]
    assert not match_exec_calls(rows).matched


def test_the_hint_goes_once_literal_calls_match_again():
    rows = [_previous_write(T0), _readme_read(T0 + timedelta(seconds=2)),
            _exec('const f="README.md"; await tools.exec_command({cmd:`cat ${f}`})', T0 + timedelta(seconds=5)),
            _readme_read(T0 + timedelta(seconds=7)),
            _exec('text(await tools.exec_command({cmd:"cat README.md"}))', T0 + timedelta(seconds=9))]
    matched = match_exec_calls(rows)
    assert len(matched.matched) == 1 and len(matched.unmatched) == 1
    blocked = {"state": "blocked", "detail": "not done"}
    assert with_literal_hint(blocked, matched) == blocked
    assert with_literal_hint(blocked, match_exec_calls(rows[:3]))["detail"] != "not done"


def test_a_claude_code_session_is_not_touched():
    rows = [_previous_write(T0), _readme_read(T0 + timedelta(seconds=2)),
            _exec('text(await tools.exec_command({cmd:"cat README.md"}))', T0 + timedelta(seconds=6))]
    assert codex_exec_evidence(Session(metadata_={}), rows) is None
    assert codex_exec_evidence(Session(metadata_={"engine": "claude_code"}), rows) is None
    assert codex_exec_evidence(Session(metadata_={"engine": "codex"}), rows).matched


def test_a_const_bound_to_a_literal_counts_as_a_literal_argument():
    """Codex can build its patch as ``const patch = "*** Begin Patch…"`` and call ``tools.apply_patch(patch)``;
    the spec draft must still count as written, or the phase stalls."""
    from app.services.agent_gateway.codex_exec_parser import exec_occurrences

    script = ('const patch = "*** Begin Patch\\n*** Add File: SPEC.md\\n+# Spec\\n*** End Patch";\n'
              'const r = await tools.apply_patch(patch);\ntext(r);')
    [call] = exec_occurrences(script)
    assert call.literal and call.args.startswith("*** Begin Patch")
    dynamic = 'const p = "a" + x;\nawait tools.apply_patch(p);'
    assert not exec_occurrences(dynamic)[0].literal
    twice = 'const p = "a";\n{ const p = "b"; }\nawait tools.apply_patch(p);'
    assert not exec_occurrences(twice)[0].literal
    later = 'await tools.apply_patch(p);\nconst p = "a";'
    assert not exec_occurrences(later)[0].literal
    member = 'const o = {cmd: "ls"};\nawait tools.exec_command(o.cmd);'
    assert not exec_occurrences(member)[0].literal


def test_a_secret_looking_argument_masked_by_the_recorder_keeps_the_call_literal():
    """Codex passes ``max_output_tokens:20000``; the recorder masks it as ``max_output_tokens:[redacted]``, and
    every exec_command must keep its evidence, or the read check fails."""
    rows = [_previous_write(T0), _readme_read(T0 + timedelta(seconds=2)),
            _exec('text(await tools.exec_command({cmd:"cat README.md",max_output_tokens:[redacted]}))',
                  T0 + timedelta(seconds=6))]
    matched = match_exec_calls(rows)
    assert len(matched.matched) == 1 and not matched.unmatched
    assert native_read_use(_counted(matched.rows)[0]).succeeded is True
    # A masked value never stands in for a compared argument: a masked command matches no hook.
    masked = [_previous_write(T0), _readme_read(T0 + timedelta(seconds=2)),
              _exec('text(await tools.exec_command({cmd:[redacted]}))', T0 + timedelta(seconds=6))]
    assert not match_exec_calls(masked).matched
