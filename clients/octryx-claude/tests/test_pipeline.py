"""The run's CI pipeline on the device: the declared commands without an agent, this run's screenshots only."""

from __future__ import annotations

import os
from types import SimpleNamespace

from octryx_claude import hook_evidence, hook_outputs, pipeline, pipeline_commands

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _runner(tmp_path, *, single_exit: int):
    """A non-pytest runner that fails one test (Flutter's compact line), and its single-test command."""
    (tmp_path / "test").mkdir(exist_ok=True)
    (tmp_path / "test" / "perf_test.dart").write_text("// a test\n")
    (tmp_path / "suite.sh").write_text(
        f"echo '00:27 +362 -1: {tmp_path}/test/perf_test.dart: 1000 brews: frames within 16 ms [E]'\n"
        "echo '00:28 +370 -1: Some tests failed.'\nexit 1\n")
    (tmp_path / "single.sh").write_text(f'echo "single $1 / $2"\nexit {single_exit}\n')
    return [{"commands": [["sh", "suite.sh"]], "failed": r"^\d+:\d{2} \+\d+(?: ~\d+)? -\d+: (?P<file>\S+\.dart): "
                                                         r"(?P<name>.+?) \[E\]$",
             "single": ["sh", "single.sh", "{file}", "{name}"]}]


def test_every_command_runs_and_reports_its_end_and_junit(tmp_path):
    view = {"node_id": "pipeline", "entry": 7, "path": ["bin"], "commands": [
        "mkdir -p r && echo '<testsuite/>' > r/j.xml # --junitxml=r/j.xml", "echo broken; exit 3"]}
    (tmp_path / "bin").mkdir()
    results = pipeline.run_commands(view, tmp_path)
    assert [item["exit_code"] for item in results] == [0, 3]  # a red one does not stop the next
    assert "broken" in results[1]["output_tail"] and results[0]["junit_xml"].strip() == "<testsuite/>"


def test_only_this_runs_screenshots_go_up_and_the_report_is_bound_to_the_pass(tmp_path, monkeypatch):
    old = tmp_path / "test-reports" / "screenshots"
    old.mkdir(parents=True)
    (old / "stale.png").write_bytes(PNG)
    view = {"node_id": "pipeline", "entry": 7, "path": [], "commands": [
        "mkdir -p test-reports/screenshots && cp shot.png test-reports/screenshots/home.png"]}
    (tmp_path / "shot.png").write_bytes(PNG)
    posts = []

    def call(_state, _context, method, path, **kwargs):
        posts.append((path, kwargs.get("body")))
        return SimpleNamespace(outcome="ok", body={"state": "stored"}, state="stored")

    monkeypatch.setattr(pipeline, "call_control_plane", call)
    monkeypatch.setattr(pipeline, "remember", lambda *_a: {"digest": "x", "pipeline": None})
    context = SimpleNamespace(session_key="00000000-0000-0000-0000-000000000001")
    answered = pipeline.run_for_session(None, context, {"pipeline": view}, str(tmp_path), http=None)
    shots = [body["name"] for path, body in posts if path == "/sessions/screenshots"]
    report = [body for path, body in posts if path == "/sessions/pipeline"][0]
    assert shots == ["home.png"] and (report["node_id"], report["entry"]) == ("pipeline", 7)
    assert report["results"][0]["exit_code"] == 0 and answered == {"digest": "x", "pipeline": None}
    assert pipeline.run_for_session(None, context, {"pipeline": None}, str(tmp_path), http=None) == {"pipeline": None}


def test_a_pytest_command_without_its_own_report_writes_one_and_stays_word_for_word(tmp_path):
    """``pytest -q`` names no test, so pytest writes a JUnit report through ``PYTEST_ADDOPTS``; the command stays
    word for word."""
    import sys

    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    (tests / "test_x.py").write_text("def test_ok():\n    assert True\n\n\ndef test_bad():\n    assert False\n")
    command = f"cd tests && {sys.executable} -m pytest -q -p no:cacheprovider test_x.py"
    # The platform's report_env (stacks.json, every runner's; the pipeline view always carries it).
    view = {"node_id": "pipeline", "entry": 1, "path": [], "commands": [command, "echo no tests here"],
            "report_env": {"PYTEST_ADDOPTS": "--junitxml={report}"}}
    results = pipeline.run_commands(view, tmp_path)
    assert [item["command"] for item in results] == view["commands"]
    assert results[0]["exit_code"] == 1 and (tmp_path / "test-reports" / "pipeline-1.xml").is_file()
    assert 'name="test_ok"' in results[0]["junit_xml"] and 'name="test_bad"' in results[0]["junit_xml"]
    assert results[1]["junit_xml"] is None
    assert pipeline_commands.report_path("pytest --junitxml=out/r.xml", 1) == ("out/r.xml", False)


def test_a_red_pipeline_goes_into_the_resume_prompt_and_reruns_only_a_few_failures(tmp_path, state):
    """The red pipeline goes into the resume prompt itself, and only a few failures are re-run."""
    from types import SimpleNamespace

    from octryx_claude.device_job_run import with_pipeline_red
    from octryx_claude.platform import SessionContext

    results = [{"command": "python -m pytest -v", "exit_code": 0, "output_tail": "ok"},
               {"command": "python -m pytest -v tests/system", "exit_code": 1,
                "failed_tests": ["tests/system/test_p.py::test_form"],
                "output_tail": "\n".join(f"line {n}" for n in range(100)) + "\nE TimeoutError profile-form"}]
    summary = pipeline.red_summary(results)
    assert "tests/system/test_p.py::test_form" in summary and "TimeoutError" in summary
    assert "line 50" not in summary and "pytest -v tests/system" in summary and "(exit 1)" in summary
    key = "00000000-0000-4000-8000-0000000000ee"
    pipeline._note_red(state, SessionContext("https://x", key, "ws", "", ""), results)
    prompt = with_pipeline_red(state, SimpleNamespace(session_key=key, extra={}), "Fix the red pipeline.")
    assert prompt.startswith("Fix the red pipeline.\n\nThe CI pipeline's red result on this change:\n\n")
    assert "test_form" in prompt
    # The platform's own text (prompt catalog run.launcher.*, the contract's prompt_texts) wins over the fallback.
    pipeline._note_red(state, SessionContext("https://x", key, "ws", "", ""), results,
                       texts={"run.launcher.pipeline_red": "CI says no:\n{summary}"})
    prompt = with_pipeline_red(state, SimpleNamespace(session_key=key, extra={}), "Fix.")
    assert prompt.startswith("Fix.\n\nCI says no:\n$ python -m pytest -v tests/system")
    pipeline._note_red(state, SessionContext("https://x", key, "ws", "", ""), results[:1])  # green: nothing added
    assert with_pipeline_red(state, SimpleNamespace(session_key=key, extra={}), "p") == "p"
    assert pipeline_commands.RERUN_MAX_FAILED == 3


def test_the_report_names_the_tree_the_server_builds_from_the_reported_change(tmp_path, monkeypatch):
    """The server pushes only a tree its pipeline ran green on. The device's tree is the one the server
    gets from ``base + change`` (the patch ``run_contract.change`` reports), so the server can cross-check it."""
    import os
    import subprocess

    from octryx_claude import run_contract

    def git(*args, env=None):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True, text=True,
                              env=env).stdout.strip()

    git("init", "-q")
    git("config", "user.name", "t")
    git("config", "user.email", "t@t.invalid")
    (tmp_path / "app.py").write_text("print('base')\n")
    git("add", "-A")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (tmp_path / "app.py").write_text("print('changed')\n")
    (tmp_path / "new.py").write_text("x = 1\n")  # untracked: part of the change and of the tree
    posts = []

    def call(_state, _context, method, path, **kwargs):
        posts.append((path, kwargs.get("body")))
        return SimpleNamespace(outcome="ok", body={}, state="stored")

    monkeypatch.setattr(pipeline, "call_control_plane", call)
    monkeypatch.setattr(pipeline, "remember", lambda *_a: None)
    view = {"node_id": "pipeline", "entry": 3, "path": [], "commands": ["mkdir -p test-reports && echo ok"]}
    context = SimpleNamespace(session_key="00000000-0000-0000-0000-000000000001")
    pipeline.run_for_session(None, context, {"pipeline": view}, str(tmp_path), http=None)
    report = [body for path, body in posts if path == "/sessions/pipeline"][0]
    patch = run_contract.change(tmp_path, base)["patch"]
    index = {**os.environ, "GIT_INDEX_FILE": str(tmp_path / ".git" / "server-index")}
    git("read-tree", base, env=index)
    subprocess.run(["git", "-C", str(tmp_path), "apply", "--cached", "--binary", "-"], input=patch, text=True,
                   check=True, env=index)
    assert report["tree"] and report["tree"] == git("write-tree", env=index)


def test_a_report_the_platform_cannot_take_is_sent_again_and_then_handed_back(tmp_path, monkeypatch):
    """Story path audit: a pipeline report lost in an API restart left the pipeline pending for good, and
    the job still said "pipeline_done". It is sent again for a while; if the platform stays away, the turn is handed
    back (a transient refusal the platform offers once more)."""
    import pytest

    view = {"node_id": "pipeline", "entry": 7, "path": [], "commands": ["true"]}
    answers = []
    monkeypatch.setattr(pipeline.time, "sleep", lambda _seconds: None)

    def call(_state, _context, method, path, **kwargs):
        if path != "/sessions/pipeline":
            return SimpleNamespace(outcome="ok", body={}, state="stored", status_code=200)
        answer = answers.pop(0)
        return answer

    monkeypatch.setattr(pipeline, "call_control_plane", call)
    monkeypatch.setattr(pipeline, "remember", lambda *_a: {"digest": "x"})
    context = SimpleNamespace(session_key="00000000-0000-0000-0000-000000000001")
    down = SimpleNamespace(outcome="unreachable", body=None, state="", status_code=None)
    stored = SimpleNamespace(outcome="ok", body={"state": "stored"}, state="stored", status_code=200)
    answers.extend([down, down, stored])
    assert pipeline.run_for_session(None, context, {"pipeline": view}, str(tmp_path), http=None) == {"digest": "x"}
    assert answers == []  # sent three times
    answers.extend([down] * pipeline.REPORT_ATTEMPTS)
    with pytest.raises(pipeline.ReportLostError) as lost:
        pipeline.run_for_session(None, context, {"pipeline": view}, str(tmp_path), http=None)
    assert lost.value.code == "pipeline_report_unreachable" and answers == []


def test_a_pipeline_red_only_on_code_style_puts_the_findings_into_the_prompt(state):
    """Every command passed, only the code style is red: the findings go into the prompt, so it names what to fix."""
    from types import SimpleNamespace

    from octryx_claude.device_job_run import with_pipeline_red
    from octryx_claude.platform import SessionContext

    green = [{"command": "flutter test", "exit_code": 0, "output_tail": "All tests passed!"}]
    answer = {"state": "red", "workflow_run": {"phase": {"pipeline_failure": {"code_style_errors": [
        "dart: Changed test/features/onboarding/onboarding_s2_pages_test.dart [formatter]",
        "python: E501 Line too long (94 > 88) --> system_test/onboarding_scenarios.py:183:89 [linter]"]}}}}
    key = "00000000-0000-4000-8000-0000000000ef"
    context = SessionContext("https://x", key, "ws", "", "")
    pipeline._note_red(state, context, green)  # the commands alone: nothing to say
    pipeline._note_style_verdict(state, context, answer)
    prompt = with_pipeline_red(state, SimpleNamespace(session_key=key, extra={}), "Fix the red pipeline.")
    assert "onboarding_s2_pages_test.dart [formatter]" in prompt and "onboarding_scenarios.py:183:89" in prompt
    pipeline._note_red(state, context, green)  # the next green pass clears it
    pipeline._note_style_verdict(state, context, {"state": "green", "workflow_run": {"phase": {}}})
    assert with_pipeline_red(state, SimpleNamespace(session_key=key, extra={}), "p") == "p"


def test_a_non_pytest_runners_failed_test_runs_again_alone_and_is_flaky_when_it_passes(tmp_path):
    """A test red, then green on the same tree is flaky and costs no fix round."""
    from octryx_claude.pipeline_commands import run_command

    reruns = _runner(tmp_path, single_exit=0)
    result = run_command("sh suite.sh", 1, tmp_path, dict(os.environ), reruns)
    test_id = "test/perf_test.dart::1000 brews: frames within 16 ms"
    assert result["exit_code"] == 1 and result["failed_tests"] == [test_id]
    assert (result["rerun"]["exit_code"], result["rerun"]["tests"], result["flaky"]) == (0, [test_id], [test_id])
    assert "single test/perf_test.dart / 1000 brews: frames within 16 ms" in result["rerun"]["output_tail"]


def test_a_test_red_again_alone_is_not_flaky_and_without_a_rule_nothing_runs_again(tmp_path):
    from octryx_claude.pipeline_commands import run_command

    reruns = _runner(tmp_path, single_exit=1)
    result = run_command("sh suite.sh", 1, tmp_path, dict(os.environ), reruns)
    assert result["rerun"]["exit_code"] == 1 and result["flaky"] == []
    assert "rerun" not in run_command("sh suite.sh", 1, tmp_path, dict(os.environ), [])


def test_the_launchers_denial_texts_are_the_platforms_with_its_own_as_fallback(monkeypatch, tmp_path):
    """The launcher's texts come from the run contract's prompt_texts
    (run.launcher.*); its own copy answers a hook without a run contract (the platform unreachable)."""
    from octryx_claude import hooks
    from octryx_claude.platform import PlatformResult

    unreachable = PlatformResult("unreachable", reason="timeout")
    fallback = hook_outputs.pre_tool_use_output(unreachable)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "fail closed" in fallback and "Next:" in fallback
    platform = {"run.launcher.fail_closed": "Platform words{codes}. Next: wait."}
    output = hook_outputs.pre_tool_use_output(unreachable, texts=platform)
    told = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert told.startswith("Platform words") and told.endswith("Next: wait.")
    monkeypatch.setattr(hooks.run_contract, "current", lambda _state, _key: {"prompt_texts": platform})
    assert hook_evidence.launcher_texts(SimpleNamespace(), SimpleNamespace(session_key="k")) == platform
    assert hook_evidence.launcher_texts(SimpleNamespace(), None) == {}
