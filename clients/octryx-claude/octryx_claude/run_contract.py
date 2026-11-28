"""The workflow run an octryx-claude session follows, as the platform last described it.
It only remembers the contract and reports facts back; every decision is taken on the platform."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any

from .contract_change import (
    FILE_TOOLS,
    change,
)
from .contract_notices import (
    summary,
)
from .contract_sizes import line_floor, sizes
from .state import LocalState, read_json, write_private_json

CONTRACT_FILE = "workflow_run.json"
FACTS_KEY = "workflow_run_facts"
MAX_FILES = 20


def remember(state: LocalState, session_key: str, body: dict[str, Any] | None) -> dict[str, Any] | None:
    contract = (body or {}).get("workflow_run")
    if isinstance(contract, dict) and contract.get("digest"):
        write_private_json(state.session_dir(session_key) / CONTRACT_FILE, contract)
        return contract
    return None


def current(state: LocalState, session_key: str) -> dict[str, Any] | None:
    contract = read_json(state.session_dir(session_key) / CONTRACT_FILE)
    return contract if isinstance(contract, dict) and contract.get("digest") else None


def project_root(cwd: str = "") -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd or ".").resolve()


def _digest(path: Path) -> str | None:
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


MAX_TEST_TEXT = 200_000  # the server's bound (octryx/facts); a larger confirmed test file is compared by bytes


def _small_text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
        return data.decode("utf-8") if len(data) <= MAX_TEST_TEXT else None
    except (OSError, UnicodeDecodeError):
        return None


def _edit_target(hook_input: dict[str, Any], root: Path) -> Path | None:
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    raw = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    if hook_input.get("tool_name") not in FILE_TOOLS or not raw:
        return None
    base = Path(str(hook_input.get("cwd") or root))
    return Path(os.path.realpath(raw if os.path.isabs(raw) else base / raw))


def resolved_path(hook_input: dict[str, Any], root: Path) -> str | None:
    target = _edit_target(hook_input, root)
    if target is None:
        return None
    real_root = Path(os.path.realpath(root))
    return target.relative_to(real_root).as_posix() if target.is_relative_to(real_root) else ".."


def _environment_names(root: Path) -> set[str]:
    names = set(sys.stdlib_module_names)
    venvs = [Path(os.environ["VIRTUAL_ENV"])] if os.environ.get("VIRTUAL_ENV") else []
    for venv in [*venvs, root / ".venv", root / "venv"]:
        for site in venv.glob("lib/python*/site-packages"):
            for entry in site.iterdir():
                if entry.name.endswith((".dist-info", ".egg-info")):
                    top = entry / "top_level.txt"
                    names.update(top.read_text(errors="replace").split() if top.is_file() else [])
                    names.add(entry.name.split("-", 1)[0])
                elif entry.is_dir() or entry.suffix == ".py":
                    names.add(entry.name.removesuffix(".py"))
    try:
        from importlib.metadata import packages_distributions

        names.update(packages_distributions())
    except Exception:  # noqa: BLE001 - an addition, never required
        pass
    return {name.casefold().replace("-", "_") for name in names if name}


def shadows_installed(root: Path, relative: str) -> bool:
    parts = relative.casefold().split("/")
    if relative == ".." or not parts or not parts[0]:
        return True
    index = 1 if parts[0] in ("src", "lib") and len(parts) > 1 else 0
    if index >= len(parts) - 1 and not parts[index].endswith(".py"):
        return False
    path = "/".join(relative.split("/")[:index + 1])
    if (root / path).exists() or (root / f"{path}.py").exists():
        return False
    return parts[index].removesuffix(".py").replace("-", "_") in _environment_names(root)


def facts(contract: dict[str, Any] | None, *, root: Path, with_diff: bool,
          hook_input: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not contract:
        return None
    run = contract.get("run") if isinstance(contract.get("run"), dict) else {}
    node = run.get("current_node") if isinstance(run.get("current_node"), dict) else {}
    phase = contract.get("phase") if isinstance(contract.get("phase"), dict) else {}
    checked = [str(name) for name in list(phase.get("protected_files") or [])[:MAX_FILES]]
    digests: dict[str, str] = {}
    texts: dict[str, str] = {}  # for the server's layout-free fingerprint (a reformatted confirmed test stays intact)
    # A test id names its file from the app folder (test/app/x_test.dart of an app in a subfolder is not at the
    # repository root).
    environment = dict(dict(contract.get("preparation") or {}).get("environment") or {})
    app = str(environment.get("app_folder") or "").strip("/")
    for name in checked:
        for candidate in ([root / name] + ([root / app / name] if app else [])):
            path = candidate.resolve()
            if path.is_relative_to(root) and (value := _digest(path)):
                digests[name] = value
                if (text := _small_text(path)) is not None:
                    texts[name] = text
                break
    reported: dict[str, Any] = {"node_id": node.get("id"), "entry": run.get("entry"),
                                "confirmed_test_digests": digests, "confirmed_test_texts": texts,
                                "checked_files": checked}
    if hook_input is not None and (resolved := resolved_path(hook_input, root)):
        reported["resolved_path"] = resolved
        # A phase protecting confirmed tests creates new files only where it says (the server decides).
        reported["target_exists"] = bool((target := _edit_target(hook_input, root)) and target.is_file())
        reported["shadows_installed"] = shadows_installed(root, resolved)
    if with_diff and phase:
        base = str((contract.get("facts") or {}).get("base_sha") or "")
        style = phase.get("code_style") if isinstance(phase.get("code_style"), dict) else {}
        if diagrams := dict(style.get("general") or {}).get("diagrams"):
            # The diagrams' PNGs are exported before the change is taken, so they are part of it.
            from .diagram_facts import diagram_facts

            try:
                if (found := diagram_facts(root, diagrams)) is not None:
                    reported["diagrams"] = found
            except Exception:  # noqa: BLE001 - no diagram facts is no diagram verdict, never a lost Stop
                pass
        reported["change"] = change(root, base)
        if isinstance(phase.get("code_style"), dict):
            # The code style: the server compares, the launcher only counts.
            reported["sizes"] = sizes(root, base, line_floor(phase["code_style"]))
            from .style_tools import run_tools

            # Step iv: the official formatter and linter of each changed language, whatever the engine declared.
            reported["style_tools"] = run_tools(root, phase["code_style"], list(reported["sizes"].get("files") or {}),
                                                base=str(base or ""))
            from .style_l10n import l10n_facts

            reported["l10n"] = l10n_facts(root, phase["code_style"], base, list(reported["sizes"].get("files") or {}))
    return reported


def pending_notice(state: LocalState, session_key: str) -> str:
    contract = current(state, session_key)
    if not contract or not (contract.get("paused") or contract.get("waiting")):
        return ""
    return summary(contract)


__all__ = [
    "CONTRACT_FILE",
    "FACTS_KEY",
    "current",
    "facts",
    "pending_notice",
    "project_root",
    "remember",
    "resolved_path",
    "shadows_installed",
]
