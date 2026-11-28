"""How the pipeline runs one declared command (``pipeline``)."""

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
REPORT_CHARS = 2_000_000  # a verbose run's whole output is its per-test report: about a JUnit file's size
_SHELL_MARKS = ("|", ";", ">", "<", "`", "$(")
_JUNIT = re.compile(r"--junit-?xml(?:=|\s+)(\S+)")
REPORTS = "test-reports"
FAILED_ENV = "OCTRYX_PYTEST_FAILED_FILE"  # the plugin's names (``octryx_pytest``)
ONLY_ENV = "OCTRYX_PYTEST_ONLY_FILE"
RERUN_MAX_FAILED = 3


def _env(folder: Path, path: list[str], environment: dict[str, Any] | None = None) -> dict[str, str]:
    from . import tools  # noqa: PLC0415

    return tools.command_env(folder, path, environment)


def report_path(command: str, index: int) -> tuple[str, bool]:
    match = _JUNIT.search(command)
    if match:
        try:
            return shlex.split(match.group(1))[0], False
        except (ValueError, IndexError):
            return match.group(1), False
    return f"{REPORTS}/pipeline-{index}.xml", True


# node's file reporter does not create the report's folder.
def report_env_for(env: dict[str, str], report: Path, report_env: dict[str, str] | None = None) -> dict[str, str]:
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


# For a runner without a per-test report file (unittest), its flag that names every test in the output; never for a
# pipe or redirect, where the flag would land on another program.
def verbose_command(command: str, report_args: list[dict[str, Any]] | None) -> str | None:
    if not report_args or any(mark in command for mark in _SHELL_MARKS):
        return None
    words = command.split("&&")[-1].split()
    for spec in report_args:
        if any(word in words for word in spec.get("unless") or []):
            continue
        prefixes = [list(prefix) for prefix in spec.get("commands") or []]
        if any(words[at:at + len(prefix)] == prefix for prefix in prefixes for at in range(len(words))):
            return f"{command} {spec.get('add')}"
    return None


def _run_once(command: str, folder: Path, env: dict[str, str], report: str, added: bool,
              report_env: dict[str, str] | None = None, verbose: str | None = None) -> dict[str, Any]:
    started = time.time()
    try:
        run_env = _with_report(env, folder / report, report_env) if added else env
        done = subprocess.run(["/bin/sh", "-c", verbose or command], cwd=folder, env=run_env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, errors="replace", timeout=COMMAND_TIMEOUT)
        code, output = done.returncode, f"{done.stdout}\n{done.stderr}"
    except subprocess.TimeoutExpired as expired:
        code, output = 124, f"{expired.stdout or ''}\n{expired.stderr or ''}\n(timed out after {COMMAND_TIMEOUT}s)"
    xml = _junit(report, folder, started)
    # A runner that names each test's file absolutely (node's JUnit reporter): named from the folder, as pytest does.
    xml = xml.replace(f"{folder.resolve()}/", "").replace(f"{folder}/", "") if xml else xml
    files = test_report.hint_files(xml, folder, folder) if xml else []
    return {"exit_code": code, "seconds": round(time.time() - started, 1), "output_tail": str(output)[-TAIL_CHARS:],
            "junit_xml": xml, **({"junit_files": files} if files else {}),
            **({"ran": verbose, "report_text": str(output)[-REPORT_CHARS:]} if verbose and not xml else {})}


def _ids(path: Path) -> list[str]:
    try:
        return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return []


def run_command(command: str, index: int, folder: Path, env: dict[str, str],
                reruns: list[dict[str, Any]] | None = None, report_env: dict[str, str] | None = None,
                report_args: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    report, added = report_path(command, index)
    verbose = verbose_command(command, report_args)
    marks = folder / REPORTS / f".pipeline-{index}"
    failed_file, only_file = marks.with_suffix(".failed"), marks.with_suffix(".rerun")
    failed_file.unlink(missing_ok=True)
    first = _run_once(command, folder, {**env, FAILED_ENV: str(failed_file)}, report, added, report_env, verbose)
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
                      again_report, added, report_env, verbose)
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
    if result.get("exit_code") == 0 or result.get("skipped"):
        return False
    rerun = result.get("rerun") if isinstance(result.get("rerun"), dict) else {}
    return rerun.get("exit_code") != 0


def run_commands(view: dict[str, Any], folder: Path,
                 style_gate: Callable[[], str] | None = None) -> list[dict[str, Any]]:
    environment = {"browser": view["browser"]} if view.get("browser") else None
    from .build_cache import shim_env  # noqa: PLC0415

    # A build the device made for the same inputs is reused (stacks.json build_artifacts).
    env = shim_env(_env(folder, [str(item) for item in view.get("path") or []], environment),
                   view.get("build_artifacts"))
    reruns = [item for item in view.get("reruns") or [] if isinstance(item, dict)]
    report_env = {str(key): str(value) for key, value in dict(view.get("report_env") or {}).items()}
    report_args = [item for item in view.get("report_args") or [] if isinstance(item, dict)]
    expensive = str(view.get("system_test_command") or "")
    results: list[dict[str, Any]] = []
    for index, command in enumerate([str(item) for item in view.get("commands") or []], start=1):
        if expensive and command == expensive and any(_red(item) for item in results):
            results.append({"command": command, "skipped": SKIPPED_EARLIER_RED})
            continue
        if expensive and command == expensive and style_gate is not None and (why := style_gate()):
            results.append({"command": command, "skipped": f"{SKIPPED_STYLE_RED} ({why})"[:500]})
            continue
        results.append(run_command(command, index, folder, env, reruns, report_env, report_args))
    return results
