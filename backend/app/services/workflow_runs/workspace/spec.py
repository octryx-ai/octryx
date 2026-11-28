"""The repository's test environment as the run's runtimes prepare it."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from pathlib import Path, PurePosixPath
from typing import Any

ENVIRONMENT_KEY = "environment"
SOURCE_DECLARED = "declared"
SOURCE_CODING_SETUP = "coding_setup"
SOURCE_CI = "ci_derived"
SOURCE_ENVIRONMENT_FILE = "environment_file"
ENVIRONMENT_FILE_KEY = "environment_file"
MAX_ENVIRONMENT_FILE_CHARS = 200
MAX_ENVIRONMENT_FILE_BYTES = 64_000
FILE_OK, FILE_MISSING, FILE_INVALID = "ok", "missing", "invalid"
ENVIRONMENT_FILE_FORMAT = (
    'a JSON object with exactly these keys: "test" (required: the unit test command), "system_test" (the Playwright '
    'system test command), "setup" (list of commands that make the folder ready, e.g. a virtual environment), '
    '"check" (list of readiness commands, exit 0 = ready; without them the setup runs before every pipeline), '
    '"lint", "path" (list of directories relative to the app folder put first on PATH, e.g. ".venv/bin"), '
    '"browser" ("chrome" or "chromium") and "serve" ({"command", "url", "ready_seconds"}: how the built app is '
    'started for the hands-on test, on a loopback URL). Commands run with /bin/sh in the app folder; nothing may '
    "install outside it (no sudo, system package manager, global or user install).")
CI_FILES = ("bitbucket-pipelines.yml",)
MAX_COMMANDS = 10
# The browser of the system tests on a device (``octryx-claude`` ``browser``): ``chrome``, the default, is the
# device's installed Google Chrome (nothing downloaded per repository or worktree, so a setup needs
# no ``playwright install chromium``); ``chromium`` asks for Playwright's bundled browser and keeps that step.
BROWSERS = ("chrome", "chromium")
MAX_COMMAND_CHARS = 1000
MAX_CI_BYTES = 64_000
_GLOBAL_INSTALL = re.compile(
    r"(^|[\s;&|(])(sudo|doas|brew|apt|apt-get|yum|dnf|apk|port|choco|snap)\s|"
    r"\s(-g|--global|--user|--system)(\s|$)|\s--(prefix|target|root)[=\s]+(/|~|\$HOME)", re.IGNORECASE)
_PYTHON = re.compile(r"^python(?:\d+(?:\.\d+)?)?$")
_TEST_LINE = re.compile(r"^(?:\S*/)?(pytest|python3?\s+-m\s+pytest|go\s+test|npm\s+test|mvn\s+.*\btest\b|"
                        r"python3?\s+-m\s+unittest)(\s|$)")
_LINT_LINE = re.compile(r"^(flake8|ruff|pylint|eslint|black\s+--check|npm\s+run\s+lint)(\s|$)")
_INSTALL_LINE = re.compile(r"^(pip3?|python3?\s+-m\s+pip)\s+install\s+(?P<args>.+)$")


def refused_command(command: str) -> str | None:
    text = str(command or "").strip()
    if not text:
        return "an empty command"
    if len(text) > MAX_COMMAND_CHARS:
        return "longer than 1000 characters"
    if _GLOBAL_INSTALL.search(text):
        return "it installs outside the repository folder (sudo, a system package manager, a global or user install)"
    return None


def _strings(value: Any) -> list[str]:
    values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return [str(item).strip() for item in values if isinstance(item, str) and str(item).strip()][:MAX_COMMANDS]


def _relative_dirs(value: Any) -> list[str]:
    dirs = []
    for item in _strings(value):
        path = PurePosixPath(item)
        if not path.is_absolute() and ".." not in path.parts and item not in (".", ""):
            dirs.append(path.as_posix())
    return dirs


def validate_environment(raw: Any) -> tuple[dict[str, Any] | None, list[str]]:
    if raw in (None, {}, ""):
        return None, []
    if not isinstance(raw, dict):
        return None, ["environment must be an object"]
    # Defaults let the work run: a key this platform does not know yet is a warning and
    # ignored, never a reason to refuse the file; only a known key with a wrong value is an error.
    unknown = set(raw) - {"setup", "test", "lint", "path", "check", "system_test", "browser", "serve"}
    errors: list[str] = []
    warnings = [f"unknown environment key ignored: {', '.join(sorted(unknown))} (a newer platform version?)"] \
        if unknown else []
    environment = {"setup": _strings(raw.get("setup")), "test": " ".join(_strings(raw.get("test"))[:1]),
                   "lint": " ".join(_strings(raw.get("lint"))[:1]), "path": _relative_dirs(raw.get("path")),
                   "check": _strings(raw.get("check")),
                   "system_test": " ".join(_strings(raw.get("system_test"))[:1])}
    browser = str(raw.get("browser") or "").strip().lower()
    if browser in BROWSERS:
        environment["browser"] = browser
    elif browser:
        errors.append(f"browser is one of: {', '.join(BROWSERS)}")
    if (serve := _serve(raw.get("serve"), errors, warnings)) is not None:
        environment["serve"] = serve
    if len(_strings(raw.get("path"))) != len(environment["path"]):
        errors.append("path entries are directories inside the repository folder (relative, no '..')")
    for command in [*environment["setup"], *environment["check"], environment["test"], environment["lint"],
                    environment["system_test"]]:
        if command and (why := refused_command(command)):
            errors.append(f"'{command[:80]}' is refused: {why}")
    if not environment["test"]:
        errors.append("environment.test (the test command) is required")
    if warnings:
        environment["warnings"] = warnings  # shown in the run (environment_file_warning), never blocking
    return environment, errors


# The hands-on test: how the built app is served on the device, loopback only. ``command`` runs in
# the app folder and keeps running (a dev server, ``python3 -m http.server`` over a web build); the test opens ``url``
# once it answers, within ``ready_seconds`` (default 180, a first web build takes a while).
SERVE_URL = re.compile(r"^http://(127\.0\.0\.1|localhost):\d{2,5}(/[^\s]*)?$")
MAX_READY_SECONDS = 900


def _serve(raw: Any, errors: list[str], warnings: list[str] | None = None) -> dict[str, Any] | None:
    if raw in (None, {}, ""):
        return None
    if not isinstance(raw, dict):
        errors.append("serve is an object with command, url, ready_seconds, parallel and persistent")
        return None
    if unknown := set(raw) - {"command", "url", "ready_seconds", "parallel", "persistent"}:
        if warnings is not None:
            warnings.append(f"unknown serve key ignored: {', '.join(sorted(unknown))} (a newer platform version?)")
    if "persistent" in raw and type(raw["persistent"]) is not bool:
        errors.append("serve.persistent is true or false (false: the app keeps no data across a restart)")
    if "parallel" in raw and type(raw["parallel"]) is not bool:
        errors.append("serve.parallel is true or false (false: the hands-on scenarios run one at a time)")
    command = " ".join(_strings(raw.get("command"))[:1])
    url = str(raw.get("url") or "").strip()
    ready = raw.get("ready_seconds", 180)
    if not command:
        errors.append("serve.command (how the app is started) is required")
    elif why := refused_command(command):
        errors.append(f"'{command[:80]}' is refused: {why}")
    if not SERVE_URL.match(url):
        errors.append("serve.url is a loopback address with its port, e.g. http://127.0.0.1:8080/")
    if type(ready) is not int or not 1 <= ready <= MAX_READY_SECONDS:
        errors.append(f"serve.ready_seconds is 1 to {MAX_READY_SECONDS}")
        ready = 180
    # parallel false: an app whose scenarios share a server's data runs them one at a time.
    return {"command": command, "url": url, "ready_seconds": ready,
            **({"parallel": False} if raw.get("parallel") is False else {}),
            # persistent false: the app keeps no data across a restart; scenarios seed in-session.
            **({"persistent": False} if raw.get("persistent") is False else {})}


def validate_environment_file(raw: Any) -> tuple[str | None, list[str]]:
    if raw in (None, ""):
        return None, []
    text = str(raw).strip() if isinstance(raw, str) else ""
    path = PurePosixPath(text)
    if not text or len(text) > MAX_ENVIRONMENT_FILE_CHARS or path.is_absolute() or ".." in path.parts or (
            "\\" in text) or not text.endswith(".json") or path.name == ".json":
        return None, ["environment_file is a repository-relative path to a .json file (no '..', at most 200 "
                      "characters), e.g. app/.octryx/environment.json"]
    return path.as_posix(), []


def app_folder(environment_file: str) -> str:
    parent = PurePosixPath(environment_file).parent
    folder = parent.parent if parent.name == ".octryx" else parent
    return folder.as_posix() or "."


def environment_file_of(setup: dict[str, Any]) -> str | None:
    path, errors = validate_environment_file(setup.get(ENVIRONMENT_FILE_KEY))
    return None if errors else path


def read_environment_file(root: Path, environment_file: str) -> dict[str, Any]:
    # A file outside root through a link is invalid.
    found: dict[str, Any] = {"file": environment_file, "app_folder": app_folder(environment_file), "errors": []}
    base = Path(root).resolve()
    target = (base / environment_file).resolve()
    if not target.is_relative_to(base):
        return {**found, "state": FILE_INVALID, "errors": ["the file resolves outside the repository folder"]}
    if not target.is_file():
        return {**found, "state": FILE_MISSING}
    data = target.read_bytes()
    found["sha256"] = hashlib.sha256(data).hexdigest()
    if len(data) > MAX_ENVIRONMENT_FILE_BYTES:
        return {**found, "state": FILE_INVALID, "errors": ["the file is larger than 64 KB"]}
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        return {**found, "state": FILE_INVALID, "errors": [f"not valid JSON: {error}"[:300]]}
    environment, errors = validate_environment(raw)
    if environment is None and not errors:
        errors = ["environment.test (the test command) is required"]
    if errors:
        return {**found, "state": FILE_INVALID, "errors": errors}
    return {**found, "state": FILE_OK, "environment": environment}


def declared_environment(setup: dict[str, Any]) -> dict[str, Any] | None:
    raw = setup.get(ENVIRONMENT_KEY)
    if isinstance(raw, dict):
        environment, _errors = validate_environment(raw)
        return {**environment, "source": SOURCE_DECLARED} if environment and environment["test"] else None
    tests = _strings(setup.get("test_commands"))
    if not tests:
        return None
    return {"setup": _strings(setup.get("setup_commands")), "test": tests[0],
            "lint": " ".join(_strings(setup.get("lint_commands"))[:1]), "path": [], "check": [],
            "system_test": " ".join(_strings(setup.get("system_test_commands"))[:1]),
            "source": SOURCE_CODING_SETUP}


def _ci_lines(document: Any) -> list[str]:
    pipelines = dict(document.get("pipelines") or {}) if isinstance(document, dict) else {}
    candidates = [pipelines.get("default"), *dict(pipelines.get("pull-requests") or {}).values(),
                  *dict(pipelines.get("branches") or {}).values()]
    for steps in candidates:
        lines = []
        for entry in steps if isinstance(steps, list) else []:
            step = entry.get("step") if isinstance(entry, dict) else None
            for line in (step or {}).get("script") or [] if isinstance(step, dict) else []:
                if isinstance(line, str):
                    lines.extend(part.strip() for part in line.split("&&") if part.strip())
        if lines:
            return lines
    return []


def derive_from_ci(files: dict[str, str]) -> dict[str, Any] | None:
    # A proposal: its setup is never executed.
    import yaml

    for name in CI_FILES:
        text = str(files.get(name) or "")[:MAX_CI_BYTES]
        try:
            lines = _ci_lines(yaml.safe_load(text)) if text else []
        except yaml.YAMLError:
            lines = []
        test = next((line for line in lines if _TEST_LINE.match(line)), "")
        if not test:
            continue
        lint = next((line for line in lines if _LINT_LINE.match(line)), "")
        installs = [match["args"] for line in lines if (match := _INSTALL_LINE.match(line))]
        python = bool(installs) or "pytest" in test
        setup = (["python3 -m venv .venv", *(f".venv/bin/pip install {args}" for args in installs)]
                 if python else [line for line in lines[:lines.index(test)] if not _LINT_LINE.match(line)])
        return {"setup": setup[:MAX_COMMANDS], "test": test, "lint": lint, "path": [".venv/bin"] if python else [],
                "check": [], "source": SOURCE_CI, "derived_from": name}
    return None


def probes(environment: dict[str, Any]) -> list[dict[str, Any]]:
    # Argv lists, never a shell.
    if environment.get("check"):
        return [{"what": f"readiness check '{command[:120]}'", "shell": command} for command in environment["check"]]
    found: list[dict[str, Any]] = []
    for label in ("test", "lint"):
        command = str(environment.get(label) or "").split("&&")[-1].strip()
        try:
            words = [word for word in shlex.split(command) if "=" not in word.split("/")[0]]
        except ValueError:
            words = []
        if not words:
            continue
        executable = words[0]
        if _PYTHON.match(executable.rsplit("/", 1)[-1]) and len(words) > 2 and words[1] == "-m":
            module = words[2]
            found.append({"what": f"{label}: {executable} -m {module}", "argv": [
                executable, "-c", f"import importlib.util,sys;sys.exit(0 if importlib.util.find_spec({module!r}) "
                                  "else 3)"]})
        else:
            found.append({"what": f"{label}: {executable}", "which": executable})
    return found


def local_excludes(environment: dict[str, Any] | None) -> list[str]:
    if not environment:
        return []
    tops = {PurePosixPath(str(item)).parts[0] for item in environment.get("path") or []
            if str(item).strip() and not str(item).startswith("/")}
    patterns = [f"/{top}/" for top in sorted(tops) if top not in (".", "..")]
    try:
        words = shlex.split(str(environment.get("test") or ""))
    except ValueError:
        words = []
    for index, word in enumerate(words):
        target = next((word.split("=", 1)[1] for option in ("--junitxml", "--junit-xml")
                       if word.startswith(option + "=")), None)
        if target is None and word in ("--junitxml", "--junit-xml") and index + 1 < len(words):
            target = words[index + 1]
        parts = PurePosixPath(target).parts if target and not target.startswith("/") else ()
        if parts and ".." not in parts:
            pattern = f"/{parts[0]}/" if len(parts) > 1 else f"/{parts[0]}"
            patterns += [pattern] if pattern not in patterns else []
    return patterns


def runtime_environment(environment: dict[str, Any] | None) -> dict[str, Any] | None:
    if not environment:
        return None
    if environment.get("source") == SOURCE_ENVIRONMENT_FILE:
        # Only the pointer: the runtime reads the file in its own folder at preparation and pipeline time. The empty
        # command fields read as "no tests" to an agent: ``commands`` says where they are.
        file = environment["environment_file"]
        return {"source": SOURCE_ENVIRONMENT_FILE, "environment_file": file,
                "app_folder": environment["app_folder"], "setup": [], "path": [], "probes": [], "test": "",
                "lint": "", "exclude": [],
                "commands": f"read from {file} on the device (its setup, test, lint and system_test entries; the "
                            "fields here stay empty by design)"}
    declared = environment.get("source") in (SOURCE_DECLARED, SOURCE_CODING_SETUP)
    return {"source": environment.get("source"), "setup": list(environment.get("setup") or []) if declared else [],
            "path": list(environment.get("path") or []), "probes": probes(environment),
            "test": environment.get("test"), "lint": environment.get("lint"),
            **({"system_test": environment["system_test"]} if declared and environment.get("system_test") else {}),
            **({"browser": environment["browser"]} if declared and environment.get("browser") else {}),
            "exclude": local_excludes(environment),
            **({"proposal": environment} if not declared else {})}


async def environment_for_run(db: Any, run: Any) -> dict[str, Any] | None:
    from pathlib import Path

    from ..platform.repo_ref import _record, _setup, parse_repository
    from ..test_runs import working_copy_root
    from .run_app import record_default, run_environment_file

    ref = parse_repository(run.repository)
    setup = _setup(await _record(db, run, ref)) if ref is not None else {}
    pointer = run_environment_file(run) or record_default(run, environment_file_of(setup))
    if pointer:
        # The repository's own file is the law (``environment_file``): read in the server's copy when there is one;
        # a device's launcher reads it in its folder (the pointer goes to it with ``runtime_environment``).
        from .contract_pin import pin, pin_server_read

        pinned = pin(run)
        if pinned and pinned.get("file") == pointer and isinstance(pinned.get("environment"), dict):
            # The run's contract as pinned at its first valid read (``contract_pin``), never the tree's later state.
            read = {"file": pointer, "app_folder": app_folder(pointer), "state": FILE_OK, "errors": [],
                    "environment": pinned["environment"], "sha256": pinned["sha256"]}
        else:
            root = await working_copy_root(db, run)
            read = read_environment_file(root, pointer) if root is not None else {
                "file": pointer, "app_folder": app_folder(pointer), "state": "unread", "errors": []}
            pin_server_read(run, read)
        return {**dict(read.get("environment") or {}), "source": SOURCE_ENVIRONMENT_FILE,
                "environment_file": pointer, "app_folder": read["app_folder"], "file_state": read["state"],
                **({"file_errors": read["errors"]} if read["errors"] else {})}
    declared = declared_environment(setup)
    if declared:
        return declared
    root = await working_copy_root(db, run)
    files = {}
    for name in CI_FILES:
        path = Path(root) / name if root is not None else None
        if path is not None and path.is_file():
            files[name] = path.read_text(encoding="utf-8", errors="replace")[:MAX_CI_BYTES]
    return derive_from_ci(files)


async def expected_repository(db: Any, run: Any) -> dict[str, Any] | None:
    # The server checks the reported remote again either way.
    from ...agent_gateway.repository_root import connection_hosts
    from ..platform.repo_ref import parse_repository

    ref = parse_repository(run.repository)
    hosts = await connection_hosts(db, run, ref.provider, ref.args()) if ref is not None else set()
    return {"provider": ref.provider, "hosts": sorted(hosts), "path": ref.path.lower()} if hosts else None


__all__ = ["BROWSERS", "ENVIRONMENT_FILE_FORMAT", "ENVIRONMENT_FILE_KEY", "ENVIRONMENT_KEY", "SOURCE_CI",
           "SOURCE_CODING_SETUP", "SOURCE_DECLARED", "SOURCE_ENVIRONMENT_FILE", "app_folder", "declared_environment",
           "derive_from_ci", "environment_file_of", "environment_for_run", "expected_repository", "probes",
           "read_environment_file", "refused_command", "local_excludes", "runtime_environment",
           "validate_environment", "validate_environment_file"]
