from octryx_claude import pipeline, pipeline_commands

SYSTEM = "touch system-test-started && echo system ok"


def _view(*commands: str) -> dict:
    return {"node_id": "pipeline", "entry": 1, "commands": list(commands), "system_test_command": SYSTEM}


def test_a_red_unit_test_keeps_the_system_test_from_starting(tmp_path):
    results = pipeline.run_commands(_view("echo unit failed; exit 1", SYSTEM), tmp_path)
    assert results[0]["exit_code"] == 1
    assert results[1] == {"command": SYSTEM, "skipped": pipeline_commands.SKIPPED_EARLIER_RED}
    assert not (tmp_path / "system-test-started").exists()
    summary = pipeline.red_summary(results)
    assert "unit failed" in summary and f"$ {SYSTEM}  (not run: an earlier check is red" in summary


def test_a_green_pass_runs_everything(tmp_path):
    results = pipeline.run_commands(_view("echo unit ok", SYSTEM), tmp_path)
    assert [item.get("exit_code") for item in results] == [0, 0]
    assert (tmp_path / "system-test-started").exists()


def test_other_commands_still_run_after_a_red_one_and_without_a_named_system_test_nothing_is_skipped(tmp_path):
    view = _view("exit 1", "echo lint ran", SYSTEM)
    results = pipeline.run_commands(view, tmp_path)
    assert results[1]["exit_code"] == 0 and "lint ran" in results[1]["output_tail"]
    assert results[2].get("skipped")
    plain = pipeline.run_commands({**view, "system_test_command": ""}, tmp_path)
    assert plain[2]["exit_code"] == 0 and (tmp_path / "system-test-started").exists()


def test_a_skipped_pass_is_never_remembered_as_green(tmp_path):
    results = [{"command": "unit", "exit_code": 0},
               {"command": SYSTEM, "skipped": pipeline_commands.SKIPPED_EARLIER_RED}]
    assert not pipeline_commands._red(results[1])
    assert not (bool(results) and all(item.get("exit_code") == 0 for item in results))  # remember_green's rule


# Step 2: the platform judges the code style before the system test; the device only asks.


def test_a_red_code_style_keeps_the_system_test_from_starting(tmp_path):
    asked = []
    gate = lambda: asked.append(1) or "lib/main.dart: format it (dart format)"  # noqa: E731
    results = pipeline.run_commands(_view("echo unit ok", SYSTEM), tmp_path, gate)
    assert results[0]["exit_code"] == 0 and asked == [1]
    assert results[1]["skipped"].startswith(pipeline_commands.SKIPPED_STYLE_RED)
    assert "dart format" in results[1]["skipped"]
    assert not (tmp_path / "system-test-started").exists()


def test_a_green_style_runs_the_system_test_and_a_red_unit_test_never_asks(tmp_path):
    asked = []
    results = pipeline.run_commands(_view("echo unit ok", SYSTEM), tmp_path, lambda: asked.append(1) or "")
    assert results[1]["exit_code"] == 0 and (tmp_path / "system-test-started").exists() and asked == [1]
    (tmp_path / "system-test-started").unlink()
    pipeline.run_commands(_view("exit 1", SYSTEM), tmp_path, lambda: asked.append(2) or "red")
    assert asked == [1]  # already skipped for the red unit test: no style question


class _Answer:
    def __init__(self, outcome, body):
        self.outcome, self.body = outcome, body


def _gate(monkeypatch, tmp_path, answer):
    sent = []

    def fake(_state, _context, method, path, **kwargs):
        sent.append((method, path, kwargs["body"]))
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(pipeline, "call_control_plane", fake)
    monkeypatch.setattr(pipeline, "_style_report", lambda _root, _view: {"sizes": {"files": {"a.py": 10}}})
    view = {"node_id": "pipeline", "entry": 2, "code_style": {"max_file_lines": 300}, "base": "abc"}
    style: dict = {}
    return pipeline._style_gate(None, None, view, style, tmp_path, http=None), sent, style


def test_the_platform_decides_and_any_failure_lets_the_system_test_run(monkeypatch, tmp_path):
    why, sent, style = _gate(monkeypatch, tmp_path, _Answer("ok", {"blocking": True, "errors": ["a.py: too long"]}))
    assert why == "a.py: too long"
    assert sent == [("POST", "/sessions/pipeline/style",
                     {"node_id": "pipeline", "entry": 2, "sizes": {"files": {"a.py": 10}}})]
    assert style["report"] == {"sizes": {"files": {"a.py": 10}}}  # made once, sent again with the final report
    assert _gate(monkeypatch, tmp_path, _Answer("ok", {"blocking": False}))[0] == ""
    assert _gate(monkeypatch, tmp_path, _Answer("unreachable", {}))[0] == ""
    assert _gate(monkeypatch, tmp_path, OSError("down"))[0] == ""
