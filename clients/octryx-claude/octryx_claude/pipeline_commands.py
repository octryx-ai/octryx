"""How the pipeline runs one declared command (``pipeline``).

Every command writes a JUnit report: one that names none (``--junitxml``) runs with
``PYTEST_ADDOPTS=--junitxml=test-reports/pipeline-<n>.xml``, so pytest writes it wherever the command starts it
(``cd app && pytest``, ``make test``, ``tox``) while the command's text stays exactly the declared one; a command
that runs no pytest simply writes none. The platform reads every test of the pipeline from it (``pytest -q``
prints no test name). The report goes up with the test files its classnames name (``test_report``), so
the server resolves ``tests.test_x`` to ``tests/test_x.py`` without the device's tree.

**The device's Chrome and a re-run of failed tests**: every command runs with the browser
default and the pytest plugin (``browser``: Playwright starts the installed Google Chrome, nothing is downloaded).
A red pytest command runs once more with only the tests that failed (the plugin's ``OCTRYX_PYTEST_FAILED_FILE`` and
``OCTRYX_PYTEST_ONLY_FILE``, so it works with any command form and without pytest's cache) before the pipeline
reports; the report carries that ``rerun`` (exit code, duration, output end, its JUnit report) and the ``flaky``
tests: the ones that failed and then passed with no change in between. The platform decides what that means for the
run (``workflow_runs/pipeline``), so a test that goes red and green without a code change does not send the story
back to the agent.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import test_report

COMMAND_TIMEOUT = 3600  # a guard against a hung suite, far above a real one
TAIL_CHARS = 20_000
_JUNIT = re.compile(r"--junit-?xml(?:=|\s+)(\S+)")
REPORTS = "test-reports"
FAILED_ENV = "OCTRYX_PYTEST_FAILED_FILE"  # the plugin's names (``octryx_pytest``)
ONLY_ENV = "OCTRYX_PYTEST_ONLY_FILE"
RERUN_MAX_FAILED = 3


def _env(folder: Path, path: list[str], environment: dict[str, Any] | None = None) -> dict[str, str]:
    from . import tools  # noqa: PLC0415

    return tools.command_env(folder, path, environment)


def report_path(command: str, index: int) -> tuple[str, bool]:
    """``(report, added)``: the JUnit report the command writes — its own ``--junitxml`` target, else
    ``test-reports/pipeline-<n>.xml`` that the pipeline adds through ``PYTEST_ADDOPTS``."""
    match = _JUNIT.search(command)
    if match:
        try:
            return shlex.split(match.group(1))[0], False
        except (ValueError, IndexError):
            return match.group(1), False
    return f"{REPORTS}/pipeline-{index}.xml", True


def report_env_for(env: dict[str, str], report: Path, report_env: dict[str, str] | None = None) -> dict[str, str]:
    """The environment that makes the command's runner write ``report`` (absolute: the command may ``cd`` first), its
    output unchanged: the platform's ``report_env`` of every runner (stacks.json; pytest's ``PYTEST_ADDOPTS``,
    node's ``NODE_OPTIONS`` reporters; the pipeline view always carries it, ``workflow_runs.pipeline``), each added to
    what the variable already holds. A stale report of an earlier run is removed, and the report's folder exists:
    pytest makes it, node's file reporter does not (`node --test` ended ENOENT on test-reports/, exit 7)."""
    report.unlink(missing_ok=True)
    try:
        report.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # the runner then says what it cannot write
    wanted = report_env or {}
    added = {key: " ".join(item for item in (env.get(key, "").strip(), str(value).replace("{report}", str(report)))
                           if item) for key, value in wanted.items()}
    return {**env, **added}


def _with_report(env: dict[str, str], report: Path, report_env: dict[str, str] | None = None) -> dict[str, str]:
    return report_env_for(env, report, report_env)


def _junit(report_file: str, folder: Path, started: float) -> str | None:
    report = (folder / report_file).resolve()
    try:
        if report.is_relative_to(folder) and report.stat().st_mtime >= started:
            return report.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    return None


def _run_once(command: str, folder: Path, env: dict[str, str], report: str, added: bool,
              report_env: dict[str, str] | None = None) -> dict[str, Any]:
    """One run of ``command``: exit code, duration, output end and the JUnit report it wrote."""
    started = time.time()
    try:
        run_env = _with_report(env, folder / report, report_env) if added else env
        done = subprocess.run(["/bin/sh", "-c", command], cwd=folder, env=run_env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, errors="replace", timeout=COMMAND_TIMEOUT)
        code, output = done.returncode, f"{done.stdout}\n{done.stderr}"
    except subprocess.TimeoutExpired as expired:
        code, output = 124, f"{expired.stdout or ''}\n{expired.stderr or ''}\n(timed out after {COMMAND_TIMEOUT}s)"
    xml = _junit(report, folder, started)
    # A runner that names each test's file absolutely (node's JUnit reporter): named from the folder, as pytest does.
    xml = xml.replace(f"{folder.resolve()}/", "").replace(f"{folder}/", "") if xml else xml
    files = test_report.hint_files(xml, folder, folder) if xml else []
    return {"exit_code": code, "seconds": round(time.time() - started, 1), "output_tail": str(output)[-TAIL_CHARS:],
            "junit_xml": xml, **({"junit_files": files} if files else {})}


def _ids(path: Path) -> list[str]:
    try:
        return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return []


def run_command(command: str, index: int, folder: Path, env: dict[str, str],
                reruns: list[dict[str, Any]] | None = None, report_env: dict[str, str] | None = None
                ) -> dict[str, Any]:
    """The command, and once more with only its failed tests when it was red (``rerun``, ``flaky``)."""
    report, added = report_path(command, index)
    marks = folder / REPORTS / f".pipeline-{index}"
    failed_file, only_file = marks.with_suffix(".failed"), marks.with_suffix(".rerun")
    failed_file.unlink(missing_ok=True)
    first = _run_once(command, folder, {**env, FAILED_ENV: str(failed_file)}, report, added, report_env)
    result = {"command": command, **first}
    failed = _ids(failed_file) if first["exit_code"] != 0 else []
    if first["exit_code"] != 0 and not failed and reruns:
        return _rerun_singly(result, folder, env, reruns)
    if failed:
        result["failed_tests"] = failed
    if not failed or len(failed) > RERUN_MAX_FAILED:
        # A re-run tells flaky from broken only for a few failures; many failures would only run again and fail.
        return result
    only_file.parent.mkdir(parents=True, exist_ok=True)
    only_file.write_text("".join(f"{test}\n" for test in failed), encoding="utf-8")
    again_report = f"{REPORTS}/pipeline-{index}-rerun.xml" if added else report
    rerun_failed = marks.with_suffix(".rerun-failed")
    rerun_failed.unlink(missing_ok=True)
    again = _run_once(command, folder, {**env, ONLY_ENV: str(only_file), FAILED_ENV: str(rerun_failed)},
                      again_report, added, report_env)
    still = set(_ids(rerun_failed)) if again["exit_code"] != 0 else set()
    if again["exit_code"] != 0 and not still:
        still = set(failed)  # red again without naming tests (a crash, a collection error): nothing proven flaky
    result["rerun"] = {**again, "tests": failed}
    result["flaky"] = [test for test in failed if test not in still]
    return result


def _spec_for(command: str, reruns: list[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    return next((spec for spec in reruns if any(words[:len(prefix)] == list(prefix) and prefix
                                                for prefix in spec.get("commands") or [])), None)


def _relative(file: str, folder: Path) -> str | None:
    path = Path(file)
    if not path.is_absolute():
        path = folder / path
    try:
        return path.resolve().relative_to(folder.resolve()).as_posix()
    except (OSError, ValueError):
        return None  # a file outside the command's folder is never run


def _rerun_singly(result: dict[str, Any], folder: Path, env: dict[str, str],
                  reruns: list[dict[str, Any]]) -> dict[str, Any]:
    """A red run of a non-pytest runner (stack data ``test_runner.rerun``, sent as ``reruns``): its failed tests,
    read from the output, run once more one at a time with the runner's single-test argv (no shell). A test that
    passes there is ``flaky``; the platform's flaky rule decides (a frame-time
    test went red, then green on the same tree, and cost a fix round)."""
    spec = _spec_for(result["command"], reruns)
    if spec is None:
        return result
    try:
        pattern = re.compile(str(spec.get("failed") or ""), re.MULTILINE)
    except re.error:
        return result
    found: dict[str, tuple[str, str]] = {}
    for match in pattern.finditer(str(result.get("output_tail") or "")):
        file, name = _relative(match.group("file"), folder), match.group("name").strip()
        if file and name:
            found.setdefault(f"{file}::{name}", (file, name))
    if not found or len(found) > RERUN_MAX_FAILED:
        return result
    result["failed_tests"] = list(found)
    started, outputs, still = time.time(), [], []
    for test_id, (file, name) in found.items():
        argv = [str(word).replace("{file}", file).replace("{name}", name) for word in spec.get("single") or []]
        try:
            done = subprocess.run(argv, cwd=folder, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, errors="replace", timeout=COMMAND_TIMEOUT)
            code, output = done.returncode, f"{done.stdout}\n{done.stderr}"
        except (OSError, subprocess.TimeoutExpired) as error:
            code, output = 1, str(error)
        outputs.append(f"$ {shlex.join(argv)}\n{output}")
        if code != 0:
            still.append(test_id)
    result["rerun"] = {"exit_code": 1 if still else 0, "seconds": round(time.time() - started, 1),
                       "output_tail": "\n".join(outputs)[-TAIL_CHARS:], "junit_xml": None, "tests": list(found)}
    result["flaky"] = [test_id for test_id in found if test_id not in still]
    return result


SKIPPED_EARLIER_RED = "not run: an earlier check is red"
SKIPPED_STYLE_RED = "not run: the code style is red"


def _red(result: dict[str, Any]) -> bool:
    """Red after its own re-run: a passing re-run (a flaky test) does not hold the pass back here; the platform
    judges flakiness."""
    if result.get("exit_code") == 0 or result.get("skipped"):
        return False
    rerun = result.get("rerun") if isinstance(result.get("rerun"), dict) else {}
    return rerun.get("exit_code") != 0


def run_commands(view: dict[str, Any], folder: Path,
                 style_gate: Callable[[], str] | None = None) -> list[dict[str, Any]]:
    """Run the commands in their declared order. Fail fast: the system test (the environment's
    ``system_test``, minutes per pass) starts only when every command before it is green; after a red one it is
    reported as not run, so the agent fixes the fast failure first and knows the system test is still due. Every other
    command always runs, and a green pass runs everything. Step 2: before the system test,
    ``style_gate`` asks the platform whether the change's code style is red (the platform judges, the device never
    does); a non-empty answer skips it the same way."""
    environment = {"browser": view["browser"]} if view.get("browser") else None
    from .build_cache import shim_env  # noqa: PLC0415

    # A build the device made for the same inputs is reused (stacks.json build_artifacts).
    env = shim_env(_env(folder, [str(item) for item in view.get("path") or []], environment),
                   view.get("build_artifacts"))
    reruns = [item for item in view.get("reruns") or [] if isinstance(item, dict)]
    report_env = {str(key): str(value) for key, value in dict(view.get("report_env") or {}).items()}
    expensive = str(view.get("system_test_command") or "")
    results: list[dict[str, Any]] = []
    for index, command in enumerate([str(item) for item in view.get("commands") or []], start=1):
        if expensive and command == expensive and any(_red(item) for item in results):
            results.append({"command": command, "skipped": SKIPPED_EARLIER_RED})
            continue
        if expensive and command == expensive and style_gate is not None and (why := style_gate()):
            results.append({"command": command, "skipped": f"{SKIPPED_STYLE_RED} ({why})"[:500]})
            continue
        results.append(run_command(command, index, folder, env, reruns, report_env))
    return results
