"""The workflow run an octryx-claude session follows, as the platform last described it (S10).

The platform answers every hook of a run-bound session with the run contract v2 (``workflow_run``: the current
phase, its class, tools and path rules, loop i of n, what the run waits for and the link where the person
decides). This module only remembers it and reports facts back; it never decides — every decision is taken
again on the server at the next hook.

- :func:`remember`: keep the newest contract per session (private state file);
- :func:`facts`: what the launcher reports from the working copy with PreToolUse and Stop, bound to the pass of
  the contract it answers (``node_id`` + ``entry``; the server ignores a report for another pass): the content hash
  of each confirmed test file the contract names (``phase.protected_files``; a checked file that is gone is
  reported missing), the edited path after resolving symlinks, whether it exists and whether a new file would
  shadow an installed distribution, and at Stop the change
  against the run's base commit as a binary patch **with untracked files** (a temporary index), or
  ``base_unavailable``. git runs without anything the working copy configures (no hooks, fsmonitor, external diff
  or textconv);
- :func:`changed_notice`: one line when the contract changed since it was last shown (a new phase, a pause, a
  decision waiting in the platform);
- :func:`pending_notice`: the pending decision and where it is taken, for the prompt hook (a requester
  decision — user confirmation, user question, a pause — here through ``workflow_decide`` and Claude Code's permission
  prompt, or in the platform; four-eyes approvals only in the platform; watched states by nobody);
- :func:`banner`: the run banner at launch (workflow, phase, loop i/n, what it waits for);
- :func:`agent_notice`: the platform agent the session works as — the phase's agent from the
  contract (``phase.agent``), or outside a run the read-only Assistant from the registration answer
  (``platform_agent``, :func:`remember_platform_agent`); its instructions reach the model once per digest.
"""

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
    """The path an edit tool writes, symlinks resolved, relative to the repository ('..' when outside)."""
    target = _edit_target(hook_input, root)
    if target is None:
        return None
    real_root = Path(os.path.realpath(root))
    return target.relative_to(real_root).as_posix() if target.is_relative_to(real_root) else ".."


def _environment_names(root: Path) -> set[str]:
    """Top-level import names of the project's virtual environment, the launcher's interpreter and the stdlib."""
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
    """Whether a new file at ``relative`` starts a top-level package or module (its first component, or the one
    under ``src/`` / ``lib/``) that the working copy does not have yet and an installed distribution names."""
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
    """The working copy's facts the contract asks for, for the contract's pass; ``None`` without a run."""
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
