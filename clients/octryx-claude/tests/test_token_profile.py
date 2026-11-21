"""The turn's token profile from its transcript (see where tokens could be saved): each call once,
the full size of every tool result (the job event keeps 4 KB), digests instead of inputs, and parts below the
platform's event limit."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from octryx_claude.token_profile import MAX_PART_CHARS, events, turn_profile

SECRET = "sk-should-never-leave"


def _at(minutes):
    return (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _assistant(minutes, message_id, *blocks, **usage):
    return {"type": "assistant", "timestamp": _at(minutes),
            "message": {"id": message_id, "model": "claude-sonnet-5-5", "usage": usage, "content": list(blocks)}}


def _tool_use(tool_id, name, **tool_input):
    return {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}


def _result(minutes, tool_id, content, is_error=False):
    return {"type": "user", "timestamp": _at(minutes), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": content, "is_error": is_error}]}}


def _write(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))
    return path


def test_calls_count_once_results_keep_their_full_size_and_inputs_only_as_digests(tmp_path):
    big = "x" * 69_000
    main = _write(tmp_path / "main.jsonl", [
        {"type": "user", "timestamp": _at(-90), "message": {"content": "an earlier turn"}},
        _assistant(-90, "old", input_tokens=999),
        {"type": "user", "timestamp": _at(1), "message": {"content": "Phase contract " + "c" * 400}},
        _assistant(1, "m1", _tool_use("t1", "Bash", command=f"flutter test --token {SECRET}"),
                   input_tokens=5, cache_creation_input_tokens=20_000, output_tokens=40),
        _assistant(1, "m1", _tool_use("t2", "Read", file_path="/repo/lib/a.dart"),
                   input_tokens=5, cache_creation_input_tokens=20_000, output_tokens=40),
        _result(2, "t1", big),
        _result(2, "t2", [{"type": "text", "text": "abc"}, {"type": "image", "source": {}}]),
        {"type": "system", "subtype": "compact_boundary", "timestamp": _at(3)},
        _assistant(3, "m2", _tool_use("t3", "Read", file_path="/repo/lib/a.dart", offset=10),
                   input_tokens=2, cache_read_input_tokens=20_000, cache_creation_input_tokens=18_000,
                   output_tokens=10),
        _result(4, "t3", "def", is_error=True),
        _assistant(4, "m3", {"type": "text", "text": "done"}, cache_read_input_tokens=38_000, output_tokens=5),
    ])
    sub = _write(tmp_path / "agent-a1.jsonl", [_assistant(2, "s1", input_tokens=3, output_tokens=7)])
    since = datetime.now(UTC).timestamp()

    profile = turn_profile({"main": main, "agent-a1": sub}, since)

    assert profile["prompt_chars"] == len("Phase contract ") + 400
    assert profile["calls"] == [[5, 0, 20_000, 40, 0], [2, 20_000, 18_000, 10, 0], [0, 38_000, 0, 5, 0],
                                [3, 0, 0, 7, 1]]
    assert profile["compactions"] == [1]
    (bash, read, reread) = profile["tools"]
    assert bash[:3] == ["t1", "Bash", 69_000] and bash[5:] == [0, 0]
    assert read[:3] == ["t2", "Read", 3] and reread[1:3] == ["Read", 3] and reread[5:] == [1, 1]
    assert read[4] == reread[4] and read[3] != reread[3]  # the same file, other arguments
    assert SECRET not in json.dumps(profile)


def test_no_call_no_profile_and_parts_stay_below_the_event_limit(tmp_path):
    assert turn_profile({"main": _write(tmp_path / "empty.jsonl", [])}, 0) is None
    profile = {"prompt_chars": 7, "compactions": [3],
               "calls": [[100_000, 200_000, 3_000, 900, 0]] * 900,
               "tools": [["toolu_" + "a" * 24, "mcp__octryx-knowledge__workflow_run_status", 69_000,
                          "0123456789ab", "", 5, 0]] * 900}
    parts = events(profile)
    assert len(parts) > 1 and {part["parts"] for part in parts} == {len(parts)}
    assert all(len(json.dumps(part)) < MAX_PART_CHARS + 500 for part in parts)
    assert sum(len(part["calls"]) for part in parts) == 900 and sum(len(part["tools"]) for part in parts) == 900
    assert parts[0]["prompt_chars"] == 7 and "prompt_chars" not in parts[1]
