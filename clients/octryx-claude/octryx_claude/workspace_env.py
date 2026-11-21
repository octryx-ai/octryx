"""The repository's declared environment in the launch folder (``workspace_prep`` step 2): the probes, the setup
commands and the local excludes.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from . import browser
from .work_git_commit import exclude_runtime_files
from .workspace_git import _git, _ok, _out

PROBE_TIMEOUT = 60
SETUP_TIMEOUT = 900
MAX_OUTPUT = 2000
_EXCLUDE = re.compile(r"^/(?!\.\.?/?$)[A-Za-z0-9._-]+/?$")  # one top-level name of the folder, nothing else
# The platform validates declared commands; the device refuses these on its own as well.
_OUTSIDE = re.compile(r"(^|[\s;&|(])(sudo|doas|brew|apt|apt-get|yum|dnf|apk|port|choco|snap)\s|"
                      r"\s(-g|--global|--user|--system)(\s|$)|\s--(prefix|target|root)[=\s]+(/|~|\$HOME)", re.I)


def _dirs(root: Path, path: list[Any]) -> list[str]:
    found = []
    for item in path:
        candidate = (root / str(item)).resolve()
        if str(item) and not os.path.isabs(str(item)) and candidate.is_relative_to(root):
            found.append(str(candidate))
    return found


def environment_env(root: Path, environment: dict[str, Any], parent: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if parent is None else parent)
    dirs = _dirs(root, list(environment.get("path") or []))
    env["PATH"] = os.pathsep.join([*dirs, env.get("PATH", "")])
    env.update({"PIP_REQUIRE_VIRTUALENV": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
    if dirs:
        env["VIRTUAL_ENV"] = str(Path(dirs[0]).parent)
    browser.apply(env, environment)  # the device's Chrome for Playwright, the pytest plugin
    return env


def _run(argv: list[str], root: Path, env: dict[str, str], timeout: int) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True, timeout=timeout, check=False,
                              stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return 127, f"{argv[0]}: command not found"
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout} s"
    except OSError as exc:
        return 126, f"{argv[0]}: {exc.strerror or 'cannot run'}"
    return done.returncode, ((done.stdout or "") + (done.stderr or ""))[-MAX_OUTPUT:]


def _probe(root: Path, probe: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    what = str(probe.get("what") or "")[:200]
    if probe.get("which"):
        name = str(probe["which"])
        found = ((root / name).is_file() and os.access(root / name, os.X_OK)) if "/" in name else bool(
            shutil.which(name, path=env["PATH"]))
        return {"what": what, "ok": found, "detail": "" if found else f"{name}: command not found"}
    argv = ["/bin/sh", "-c", str(probe["shell"])] if probe.get("shell") else [str(item) for item in probe.get("argv")
                                                                               or []]
    if not argv:
        return {"what": what, "ok": False, "detail": "no probe"}
    code, output = _run(argv, root, env, PROBE_TIMEOUT)
    detail = output.strip()[-300:] or (f"exit {code}" if code else "")
    if code == 3 and not probe.get("shell"):
        detail = f"module '{what.rsplit(' ', 1)[-1]}' is not installed for {argv[0]}"
    return {"what": what, "ok": code == 0, "detail": detail}


def exclude_environment(root: Path, path: list[Any], patterns: list[Any] | None = None) -> None:
    """The environment's directories (``.venv``) and the test report never become part of the change: a local
    exclude, not a commit (``patterns`` as the server derived them, else the ``path`` directories)."""
    tops = sorted({Path(str(item)).parts[0] for item in path if str(item) and not os.path.isabs(str(item))})
    wanted = [str(item) for item in patterns if _EXCLUDE.match(str(item))] if patterns else [
        f"/{top}/" for top in tops if top not in ("", ".", "..")]
    target = _git(root, "rev-parse", "--git-path", "info/exclude")
    if not wanted or not _ok(target):
        return
    exclude = root / _out(target)
    lines = exclude.read_text().splitlines() if exclude.is_file() else []
    missing = [pattern for pattern in wanted if pattern not in lines]
    if missing:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("\n".join([*lines, *missing]) + "\n")


def prepare_environment(root: Path, environment: dict[str, Any] | None) -> dict[str, Any]:
    exclude_runtime_files(root)  # test reports, caches, venvs and databases never enter the change (M1)
    if not environment:
        return {"state": "not_declared", "probes": [], "setup": []}
    if environment.get("environment_file"):
        return prepare_from_file(root, environment)
    exclude_environment(root, list(environment.get("path") or []), list(environment.get("exclude") or []))
    env = environment_env(root, environment)
    probes = [probe for probe in environment.get("probes") or [] if isinstance(probe, dict)]
    results = [_probe(root, probe, env) for probe in probes]
    setup_log: list[dict[str, Any]] = []
    if not all(item["ok"] for item in results) and environment.get("setup"):
        for command in [str(item) for item in environment["setup"]]:
            if browser.skips_setup(command, env):
                setup_log.append({"command": command, "exit_code": 0, "seconds": 0,
                                  "output": "skipped: the tests use this device's Google Chrome (browser.py)"})
                continue
            if _OUTSIDE.search(command):
                setup_log.append({"command": command, "exit_code": None, "seconds": 0,
                                  "output": "refused on this device: it installs outside the repository folder"})
                break
            started = time.monotonic()
            code, output = _run(["/bin/sh", "-c", command], root, env, SETUP_TIMEOUT)
            setup_log.append({"command": command, "exit_code": code, "output": output,
                              "seconds": round(time.monotonic() - started, 1)})
            if code != 0:
                break
        results = [_probe(root, probe, env) for probe in probes]
    failed = [item for item in results if not item["ok"]]
    if results and not failed:
        return {"state": "ready", "probes": results, "setup": setup_log}
    reason = "; ".join(f"{item['what']}: {item['detail']}" for item in failed) or "no readiness probe"
    if setup_log and setup_log[-1].get("exit_code") != 0:
        reason += f"; setup '{setup_log[-1]['command'][:120]}' failed: {str(setup_log[-1]['output']).strip()[-300:]}"
    elif not environment.get("setup"):
        reason += "; the repository declares no environment setup"
    return {"state": "not_ready", "probes": results, "setup": setup_log, "reason": reason[:1500]}


def prepare_from_file(root: Path, pointer: dict[str, Any]) -> dict[str, Any]:
    """The repository's environment file (``environment_file``): read and validated in the folder; when it is there
    and valid, the app folder is made ready (its ``check``, else its ``setup``) so the agent works with it. Never
    blocks the run: the pipeline judges the file and sends a missing or invalid one back to the agent."""
    from . import environment_file

    account = environment_file.resolve(root, str(pointer.get("environment_file") or ""), pointer.get("environment_pin"))
    environment_file.exclude(root, account)
    found = {key: account[key] for key in ("file", "app_folder", "state", "errors", "sha256") if key in account}
    if account["state"] == environment_file.OK:
        found["environment"] = account["environment"]  # the platform pins the run's contract from its first account
    log: list[dict[str, Any]] = []
    if account["state"] == environment_file.OK:
        # The file's declared commands, so the platform lets a phase run them as declared (/73:
        # the fix phase refused `flutter test` because the server never saw the file's test command).
        found["commands"] = {key: str(account["environment"].get(key) or "") for key in ("test", "lint", "system_test")
                             if str(account["environment"].get(key) or "").strip()}
        folder = environment_file.folder_of(root, account)
        ready, log = environment_file.setup(folder, account["environment"],
                                            environment_env(folder, account["environment"]))
        found["state"] = environment_file.OK if ready else environment_file.SETUP_FAILED
    return {"state": "environment_file", "probes": [], "setup": log, "environment_file": found}


def file_environment(root: Path, environment: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    """``(folder, environment)`` the agent's ``PATH`` comes from: the app folder and the file's environment when the
    repository's environment file is there and valid, else ``root`` and the platform's environment."""
    from . import environment_file

    if not environment.get("environment_file"):
        return root, environment
    account = environment_file.resolve(root, str(environment["environment_file"]), environment.get("environment_pin"))
    if account["state"] != environment_file.OK:
        return root, {}
    return environment_file.folder_of(root, account), account["environment"]
