"""Tool history compaction for prompts, runtime control message dedupe and duplicate read-only tool result detection."""

from app.agent.core.turn.tool_call_dedup import duplicate_read_only_tool_result
from app.agent.loops.response._loop_message_dedupe import append_unique_system_message, dedupe_runtime_control_messages
from app.agent.loops.runtime._loop_tools import _history_result_for_prompt


def test_history_result_for_prompt_prefers_compact_result_and_keeps_artifact_reference():
    prompt_result = _history_result_for_prompt(
        {
            "artifact_id": "artifact-1",
            "compact_result": {"status": "ok", "path": "terraform/base/irsa.tf"},
            "result": {"content": "x" * 20_000},
        },
        raw_result={"content": "x" * 20_000},
        runtime_settings={"trace_max_string": 128},
    )

    assert prompt_result["status"] == "ok"
    assert prompt_result["path"] == "terraform/base/irsa.tf"
    assert prompt_result["artifact_id"] == "artifact-1"
    assert prompt_result["_prompt_result_source"] == "compact_result"
    assert "content" not in prompt_result


def test_history_result_for_prompt_compacts_raw_result_when_no_compact_result_exists():
    prompt_result = _history_result_for_prompt(
        {"artifact_id": "artifact-2", "result": {"content": "x" * 20_000}},
        raw_result={"content": "x" * 20_000},
        runtime_settings={"trace_max_string": 128},
    )

    assert prompt_result["artifact_id"] == "artifact-2"
    assert prompt_result["_prompt_result_source"] == "compact_trace"
    assert len(prompt_result["content"]) < 300


def test_runtime_control_message_dedupe_collapses_repeated_summary_reminders():
    reminder = (
        "This cross-system summary is not complete yet. "
        "You still need to gather evidence for: bitbucket. "
        "Use the relevant tools for the missing domains before finalizing."
    )

    deduped = dedupe_runtime_control_messages(
        [
            {"role": "system", "content": "base prompt"},
            {"role": "assistant", "content": "I will gather more evidence."},
            {"role": "system", "content": reminder},
            {"role": "assistant", "content": "I will gather more evidence."},
            {"role": "system", "content": reminder},
            {"role": "system", "content": f"  {reminder}  "},
        ]
    )

    system_contents = [message["content"] for message in deduped if message["role"] == "system"]
    assert system_contents.count(reminder) == 1
    assert len(system_contents) == 2


def test_runtime_control_message_dedupe_prevents_observed_47x_reminder_loop():
    reminder = (
        "This governed coding run is still in analysis-only mode. "
        "Use `edit_workspace_file`, `multi_edit_workspace_file`, or `apply_patch_workspace` for the approved change; "
        "then run the required validation and prepare commit/PR evidence. "
        "If the approved change is unsafe or impossible, stop with an explicit blocker instead of continuing analysis."
    )
    messages = [{"role": "system", "content": "base prompt"}]

    appended = [append_unique_system_message(messages, reminder) for _ in range(47)]
    deduped = dedupe_runtime_control_messages(messages)

    assert appended == [True] + [False] * 46
    assert [message["content"] for message in deduped if message["role"] == "system"].count(reminder) == 1


def test_duplicate_read_only_tool_result_skips_exact_repeated_read():
    duplicate = duplicate_read_only_tool_result(
        tool_name="read_workspace_file",
        tool_args={"path": "terraform/base/irsa.tf"},
        turn_tool_history=[
            {
                "tool_name": "read_workspace_file",
                "params": {"path": "terraform/base/irsa.tf"},
                "result": {"path": "terraform/base/irsa.tf", "content": "module content"},
            }
        ],
    )

    assert duplicate is not None
    assert duplicate["status"] == "duplicate_skipped"
    assert duplicate["progress_quality_event"]["kind"] == "duplicate_read_only_tool_call"
    assert duplicate["progress_quality_event"]["action"] == "reuse_prior_evidence"
    assert "compact prior evidence" in duplicate["message"]
    assert duplicate["prior_evidence"]["content_excerpt"] == "module content"
    assert duplicate["prior_evidence"]["path"] == "terraform/base/irsa.tf"


def test_duplicate_read_only_tool_result_allows_distinct_paths_and_write_tools():
    history = [
        {
            "tool_name": "read_workspace_file",
            "params": {"path": "terraform/base/irsa.tf"},
            "result": {"path": "terraform/base/irsa.tf", "content": "module content"},
        }
    ]

    assert (
        duplicate_read_only_tool_result(
            tool_name="read_workspace_file",
            tool_args={"path": "terraform/base/removed.txt"},
            turn_tool_history=history,
        )
        is None
    )
    assert (
        duplicate_read_only_tool_result(
            tool_name="edit_workspace_file",
            tool_args={"path": "terraform/base/irsa.tf"},
            turn_tool_history=[{**history[0], "tool_name": "edit_workspace_file"}],
        )
        is None
    )


def test_duplicate_read_after_a_workspace_edit_reads_again():
    read = {"tool_name": "read_workspace_file", "params": {"path": "tests/test_textkit.py"},
            "result": {"path": "tests/test_textkit.py", "content": "before the edit"}}
    edit = {"tool_name": "edit_workspace_file", "params": {"path": "tests/test_textkit.py"},
            "result": {"status": "edited"}}
    grep = {"tool_name": "grep_workspace", "params": {"pattern": "x"}, "result": {"matches": []}}

    for mutation in (edit, {**edit, "tool_name": "multi_edit_workspace_file"}, {**edit, "tool_name": "run_cli_command"}):
        assert duplicate_read_only_tool_result(
            tool_name="read_workspace_file", tool_args={"path": "tests/test_textkit.py"},
            turn_tool_history=[read, mutation, grep]) is None
    # Without a change in between the exact repeat is still skipped.
    assert duplicate_read_only_tool_result(
        tool_name="read_workspace_file", tool_args={"path": "tests/test_textkit.py"},
        turn_tool_history=[edit, read, grep])["status"] == "duplicate_skipped"


def test_duplicate_read_of_content_beyond_the_excerpt_reads_again():
    long_content = "line\n" * 1200
    history = [{"tool_name": "read_workspace_file", "params": {"path": "big.py"},
                "result": {"path": "big.py", "content": long_content}}]

    assert duplicate_read_only_tool_result(
        tool_name="read_workspace_file", tool_args={"path": "big.py"}, turn_tool_history=history) is None
