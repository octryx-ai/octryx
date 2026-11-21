"""The Anthropic-shaped view of a Responses request: what the content scan, budget and transcript read."""

from __future__ import annotations

from app.services.model_gateway.inbound.openai_view import anthropic_view
from app.services.model_gateway.inbound.turn_delta import newest_turn, scanned_texts


def test_parallel_tool_calls_and_their_outputs_form_one_turn():
    view = anthropic_view({
        "model": "octryx-general",
        "instructions": "be brief",
        "max_output_tokens": 256,
        "tools": [{"type": "function", "name": "shell"}, {"type": "web_search"}],
        "input": [
            {"role": "developer", "content": "sandbox: workspace-write"},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "go"},
                                                            {"type": "input_image", "image_url": "data:..."}]},
            {"type": "reasoning", "summary": [{"type": "summary_text", "text": "thinking"}]},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Running."}]},
            {"type": "function_call", "call_id": "a", "name": "shell", "arguments": '{"command": ["ls"]}'},
            {"type": "custom_tool_call", "call_id": "b", "name": "apply_patch", "input": "*** Begin Patch"},
            {"type": "function_call_output", "call_id": "a", "output": "README.md"},
            {"type": "custom_tool_call_output", "call_id": "b", "output": "ok"},
        ],
    })

    assert (view["system"], view["max_tokens"]) == ("be brief", 256)
    assert view["tools"] == [{"name": "shell"}, {"name": "web_search"}]
    assert [message["role"] for message in view["messages"]] == ["system", "user", "assistant", "user"]
    delta = newest_turn(view["messages"])
    # Codex's shell and patch calls are recorded under the names the evidence reads (Claude Code's)
    assert [(use.tool_use_id, use.name) for use in delta.prior_tool_uses] == [("a", "Bash"), ("b", "Edit")]
    assert delta.prior_tool_uses[0].input == {"command": "ls"}  # the command as one string, as for Bash
    assert delta.prior_tool_uses[1].input == {"input": "*** Begin Patch"}
    assert [(result.tool_use_id, result.text) for result in delta.tool_results] == [("a", "README.md"), ("b", "ok")]


def test_an_unknown_input_item_is_still_scanned():
    view = anthropic_view({"model": "m", "input": [{"type": "future_item", "payload": "AKIA-lookalike"}]})

    assert any("AKIA-lookalike" in text for text in scanned_texts(view))
    assert newest_turn(view["messages"]).prompt_text() == ""


def test_a_string_input_is_the_user_prompt():
    view = anthropic_view({"model": "m", "input": "hello", "stream": True})

    assert newest_turn(view["messages"]).prompt_text() == "hello"
    assert view["stream"] is True and "tools" not in view


def test_codex_calls_get_the_names_and_inputs_the_evidence_reads():
    from app.services.model_gateway.inbound.openai_view import evidence_names

    assert evidence_names("exec_command", {"cmd": "/bin/zsh -lc 'pytest -q'"}) == (
        "Bash", {"cmd": "/bin/zsh -lc 'pytest -q'", "command": "pytest -q"})
    assert evidence_names("shell", {"command": ["bash", "-lc", "ls"]})[1]["command"] == "ls"  # unwrapped
    patch = "*** Begin Patch\n*** Add File: docs/spec.md\n+# Spec\n*** End Patch"
    assert evidence_names("apply_patch", {"input": patch}) == ("Edit", {"input": patch, "file_path": "docs/spec.md"})
    assert evidence_names("mcp__octryx_knowledge__workflow_catalog", {}) == (
        "mcp__octryx-knowledge__workflow_catalog", {})  # the platform's MCP name
    view = anthropic_view({"model": "m", "input": [
        {"type": "function_call", "call_id": "c", "namespace": "mcp__octryx_knowledge",
         "name": "workflow_run_status", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c", "output": "{}"}]})
    assert newest_turn(view["messages"]).prior_tool_uses[0].name == (
        "mcp__octryx-knowledge__workflow_run_status")


def test_a_shell_apply_patch_is_recorded_as_the_file_change():
    from app.services.model_gateway.inbound.openai_view import evidence_names

    script = "apply_patch <<'PATCH'\n*** Begin Patch\n*** Add File: SPEC.md\n+# Spec\n*** End Patch\nPATCH"
    name, recorded = evidence_names("exec_command", {"cmd": f"/bin/zsh -lc \"{script}\""})
    assert name == "Edit" and recorded["file_path"] == "SPEC.md"
    assert evidence_names("exec_command", {"cmd": "cat SPEC.md"})[0] == "Bash"


def test_a_denied_or_failed_codex_call_is_an_error_and_a_broken_shell_patch_no_edit():
    """A hook-denied ``apply_patch {json}`` is never recorded as a successful Edit."""
    from app.services.model_gateway.inbound.openai_view import _tool_result, evidence_names

    denied = _tool_result({"call_id": "c1", "output": "Command blocked by PreToolUse hook: Octryx policy denied"})
    failed = _tool_result({"call_id": "c2", "output": "Chunk ID: x\nProcess exited with code 1\nOutput:\nboom"})
    passed = _tool_result({"call_id": "c3", "output": "Chunk ID: x\nProcess exited with code 0\nOutput:\nok"})
    assert denied["is_error"] is True and failed["is_error"] is True and "is_error" not in passed
    broken = 'apply_patch {"command":["apply_patch","*** Begin Patch\\n*** Create File: SPEC.md\\n*** End Patch"]}'
    assert evidence_names("exec_command", {"cmd": broken})[0] == "Bash"


def test_view_image_is_recorded_as_a_read():
    from app.services.model_gateway.inbound.openai_view import evidence_names

    assert evidence_names("view_image", {"path": "shots/a.png"}) == ("Read", {"file_path": "shots/a.png"})
