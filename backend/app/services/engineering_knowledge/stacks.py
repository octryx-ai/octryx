"""The stacks an app is built with, as data (``stacks.json`` next to the Engineering Knowledge Packs; a pack's
``stack_key`` names one): its manifests, code suffixes, build and cache folders, l10n catalogs and app facts.

Levels: the built-in file, then the installation's (system config ``stacks``, a JSON object) and the Workspace's
(``Project.config["stacks"]``), merged per stack key, the more specific level winning; an entry ``null`` removes a
stack. Engine code reads only these helpers, never a file, folder or language name of its own.
"""

from __future__ import annotations

import json
import re
from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path
from typing import Any

INSTALLATION_KEY = "stacks"
WORKSPACE_KEY = "stacks"


@lru_cache(maxsize=1)
def _file() -> dict[str, Any]:
    return json.loads(Path(__file__).with_name("stacks.json").read_text(encoding="utf-8"))


def built_in() -> dict[str, Any]:
    """``{"general": {...}, "stacks": {key: entry}}`` as shipped."""
    data = _file()
    return {"general": dict(data["general"]), "stacks": dict(data["stacks"])}


def merged(*levels: Any) -> dict[str, Any]:
    """The built-in stacks with each level's ``{key: entry | null}`` on top (least specific level first)."""
    out = built_in()
    for level in levels:
        for key, entry in dict(level or {}).items() if isinstance(level, dict) else []:
            if entry is None:
                out["stacks"].pop(str(key), None)
            elif isinstance(entry, dict):
                out["stacks"][str(key)] = entry
    return out


async def for_project(db: Any, project: Any) -> dict[str, Any]:
    """The stacks that apply in ``project`` (its Workspace) on this installation."""
    from ..system_config.values import get_system_config_value

    raw = await get_system_config_value(db, INSTALLATION_KEY)
    try:
        installation = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        installation = {}
    config = dict(project.config or {}) if project is not None and isinstance(project.config, dict) else {}
    return merged(installation, config.get(WORKSPACE_KEY))


def _entries(stacks: dict[str, Any] | None) -> list[dict[str, Any]]:
    found = dict((stacks or built_in()).get("stacks") or {})
    return [dict(entry) for entry in found.values() if isinstance(entry, dict)]


def manifests(stacks: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """``{file name: manifest}`` of every stack."""
    return {str(item["file"]): dict(item) for entry in _entries(stacks) for item in entry.get("manifests") or []
            if isinstance(item, dict) and item.get("file")}


def skip_folders(stacks: dict[str, Any] | None = None) -> frozenset[str]:
    """The folder names never read (build output, package caches) of every stack and the general ones."""
    general = dict((stacks or built_in()).get("general") or {})
    return frozenset([*general.get("skip_folders", []),
                      *(name for entry in _entries(stacks) for name in entry.get("skip_folders") or [])])


def code_suffixes(stacks: dict[str, Any] | None = None) -> frozenset[str]:
    return frozenset(suffix for entry in _entries(stacks) for suffix in entry.get("code_suffixes") or [])


def data_suffixes(stacks: dict[str, Any] | None = None) -> frozenset[str]:
    return frozenset(dict((stacks or built_in()).get("general") or {}).get("data_suffixes") or [])


def ui_catalogs(stacks: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The l10n catalog kinds (``glob``, ``english`` stem patterns) of every stack."""
    return [dict(item) for entry in _entries(stacks) for item in entry.get("ui_catalogs") or []
            if isinstance(item, dict)]


def is_english(path: Path, catalog: dict[str, Any]) -> bool:
    stem = path.stem.lower()
    return any(fnmatch(stem, pattern) for pattern in catalog.get("english") or [])


def is_test(relative: str, stacks: dict[str, Any] | None = None) -> bool:
    """Whether ``relative`` (a repository path) is a test: inside a test folder of a stack or the general ones, or
    named like a test of one (``tests.folders`` / ``tests.names``)."""
    data = stacks or built_in()
    rows = [dict(entry.get("tests") or {}) for entry in _entries(data)]
    rows.append(dict(dict(data.get("general") or {}).get("tests") or {}))
    parts = relative.split("/")
    folders = {str(name) for row in rows for name in row.get("folders") or []}
    if folders & set(parts[:-1]):
        return True
    return any(fnmatch(parts[-1], str(pattern)) for row in rows for pattern in row.get("names") or [])


def collection_errors(stacks: dict[str, Any] | None = None) -> list[re.Pattern[str]]:
    """The patterns (``test_output.collection_error``) of a test file that failed to load, of every stack."""
    return [re.compile(str(dict(entry.get("test_output") or {})["collection_error"])) for entry in _entries(stacks)
            if dict(entry.get("test_output") or {}).get("collection_error")]


def environment_errors(stacks: dict[str, Any] | None = None) -> tuple[frozenset[int], list[re.Pattern[str]]]:
    """The exit codes and output patterns of a command the environment could not run (``general.environment_errors``
    and every stack's ``test_output.environment_errors``); a pattern's ``module`` group names what is missing."""
    general = dict(dict((stacks or built_in()).get("general") or {}).get("environment_errors") or {})
    texts = [*list(general.get("patterns") or []),
             *(text for entry in _entries(stacks) for text in dict(entry.get("test_output") or {}).get(
                 "environment_errors") or [])]
    codes = frozenset(int(code) for code in general.get("exit_codes") or [] if type(code) is int)
    return codes, [re.compile(str(text), re.IGNORECASE | re.MULTILINE) for text in texts]


def hands_on_workers(stacks: dict[str, Any] | None = None) -> dict[str, int]:
    """``{cores_per_worker, max}``: how many hands-on scenarios a device runs at once (``general.hands_on_workers``)."""
    raw = dict(dict((stacks or built_in()).get("general") or {}).get("hands_on_workers") or {})
    return {key: int(raw[key]) for key in ("cores_per_worker", "max") if type(raw.get(key)) is int and raw[key] >= 1}


def browser_start_seconds(stacks: dict[str, Any] | None = None) -> int:
    """How long a device waits for the hands-on browser to start (``general.browser_start_seconds``; 0 = its own)."""
    value = dict((stacks or built_in()).get("general") or {}).get("browser_start_seconds")
    return value if type(value) is int and 5 <= value <= 600 else 0


def restart_settle(stacks: dict[str, Any] | None = None) -> dict[str, int]:
    """How long a device lets an app settle before a hands-on restart (``general.restart_settle``)."""
    raw = dict(dict((stacks or built_in()).get("general") or {}).get("restart_settle") or {})
    limits = {"network_idle_seconds": 60, "storage_ms": 30_000}
    return {key: raw[key] for key, most in limits.items() if type(raw.get(key)) is int and 0 <= raw[key] <= most}


def build_artifacts(stacks: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every stack's reusable builds (``build_artifacts``: tool, args, ignore_args, output, inputs)."""
    return [dict(item) for entry in _entries(stacks) for item in entry.get("build_artifacts") or []
            if isinstance(item, dict) and item.get("tool") and item.get("output") and item.get("inputs")]


def touches_ui(paths: list[str], stacks: dict[str, Any] | None = None) -> bool:
    """Whether a changed repository path is part of what a person sees (every stack's ``ui_paths``)."""
    patterns = [re.compile(str(text)) for entry in _entries(stacks) for text in entry.get("ui_paths") or []]
    return any(pattern.search(path) for path in paths for pattern in patterns)


def test_runners(stacks: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The test runners (``commands`` prefixes, ``flags``, ``value_options``, ``evidence_args``) of every stack."""
    return [dict(entry["test_runner"]) for entry in _entries(stacks) if isinstance(entry.get("test_runner"), dict)]


def runner_options_allowed(prefix: tuple[str, ...], arguments: tuple[str, ...],
                           stacks: dict[str, Any] | None = None) -> bool | None:
    """Whether ``arguments`` after a runner's ``prefix`` are its allowed options and test paths: ``None`` when no
    stack declares the runner (the caller's own rule applies). Test paths are relative repository paths."""
    runner = next((item for item in test_runners(stacks)
                   if any(tuple(command) == tuple(prefix) for command in item.get("commands") or [])), None)
    if runner is None or runner.get("options") == "any":
        return None  # no stack restricts this runner's options: the caller's own rule applies
    flags = set(runner.get("flags") or [])
    values = {str(key): re.compile(str(pattern)) for key, pattern in dict(runner.get("value_options") or {}).items()}
    index = 0
    while index < len(arguments):
        token = arguments[index]
        option, sep, value = token.partition("=")
        if token in flags:
            index += 1
        elif sep and option in values and values[option].match(value):
            index += 1
        elif token in values and index + 1 < len(arguments) and values[token].match(arguments[index + 1]):
            index += 2
        elif not token.startswith("-") and not token.startswith("/") and ".." not in token.split("/") \
                and re.fullmatch(r"[A-Za-z0-9_./-]+", token):
            index += 1
        else:
            return False
    return True


def rerun_specs(stacks: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """How a device re-runs a non-pytest runner's failed tests one at a time (``test_runner.rerun``): the runner's
    command prefixes, the output pattern of a failed test (``file``, ``name``) and the single-test argv template."""
    return [{"commands": [list(item) for item in runner.get("commands") or []],
             "failed": str(dict(runner["rerun"]).get("failed") or ""),
             "single": [str(word) for word in dict(runner["rerun"]).get("single") or []]}
            for runner in test_runners(stacks) if isinstance(runner.get("rerun"), dict)
            and dict(runner["rerun"]).get("failed") and dict(runner["rerun"]).get("single")]


def runner_for(command: str, stacks: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The test runner whose command prefix occurs in ``command`` (also after ``export …;`` or a ``cd``)."""
    words = str(command or "").replace(";", " ").replace("&&", " ").split()
    return next((runner for runner in test_runners(stacks)
                 if any(words[index:index + len(prefix)] == list(prefix) for prefix in runner.get("commands") or []
                        for index in range(len(words)))), None)


def full_run_hint(command: str, stacks: dict[str, Any] | None = None) -> str:
    """What a full run of ``command`` may add (its runner's ``full_run_hint``, else the general one)."""
    runner = runner_for(command, stacks) or {}
    general = dict((stacks or built_in()).get("general") or {})
    return str(runner.get("full_run_hint") or general.get("full_run_hint") or "")


def report_env(command: str, report: str, stacks: dict[str, Any] | None = None) -> dict[str, str]:
    """The environment that makes ``command``'s runner also write a JUnit report to ``report`` (``report_env``),
    its own output unchanged; ``{}`` for a runner without one."""
    runner = runner_for(command, stacks) or {}
    return {str(key): str(value).replace("{report}", report)
            for key, value in dict(runner.get("report_env") or {}).items()}


def all_report_env(stacks: dict[str, Any] | None = None) -> dict[str, str]:
    """Every runner's ``report_env`` in one environment (``{report}`` left for the device to fill): whichever runner a
    command starts writes the platform's per-test report, its own output unchanged."""
    found: dict[str, str] = {}
    for runner in test_runners(stacks):
        for key, value in dict(runner.get("report_env") or {}).items():
            found.setdefault(str(key), str(value))
    return found


def only_files_specs(stacks: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """How each runner runs only some test files (``test_runner.only_files``): per command prefix an argv template
    with ``{test}``, ``{prefix}``, ``{files}``, ``{basename}``, ``{modules}``, optionally only for a command that
    ``contains`` (or ``lacks``) a word or for a ``single_file``; the device fills the first that fits for the
    base-commit run."""
    return [{"commands": [list(item) for item in spec.get("commands") or []], "argv": str(spec["argv"]),
             **({"contains": str(spec["contains"])} if spec.get("contains") else {}),
             **({"lacks": str(spec["lacks"])} if spec.get("lacks") else {}),
             **({"single_file": True} if spec.get("single_file") is True else {})}
            for runner in test_runners(stacks) for spec in runner.get("only_files") or []
            if isinstance(spec, dict) and spec.get("commands") and spec.get("argv")]


def evidence_commands(stacks: dict[str, Any] | None = None) -> list[str]:
    """``<runner> <evidence_args>`` per runner that declares them (for the evidence hint)."""
    return [" ".join([*item["commands"][0], *(item.get("evidence_args") or [])]) for item in test_runners(stacks)
            if item.get("commands") and item.get("evidence_args")]


def app_facts(stacks: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The app-fact sources (``sources`` glob, ``skip_suffixes``, ``skip_folders``, ``first_start_folder``,
    ``title_pattern``) of every stack that has them."""
    return [dict(entry["app_facts"]) for entry in _entries(stacks) if isinstance(entry.get("app_facts"), dict)]


__all__ = ["all_report_env", "app_facts", "built_in", "code_suffixes", "collection_errors", "data_suffixes",
           "environment_errors", "evidence_commands", "for_project", "full_run_hint", "is_english", "is_test",
           "manifests", "merged", "only_files_specs", "report_env", "rerun_specs", "runner_for",
           "runner_options_allowed", "skip_folders", "test_runners", "ui_catalogs"]
