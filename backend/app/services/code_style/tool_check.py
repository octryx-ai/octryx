"""The official formatters' and linters' verdicts the device reports, judged against the style (``check``)."""

from __future__ import annotations

import re
from typing import Any

from .finding import Finding

MAX_TOOL_OUTPUT = 600
# The device sends a failed run's last 2,000 characters (``style_tools.MAX_OUTPUT``): that long, it may be cut.
MAX_DEVICE_OUTPUT = 2000


# How to install each official tool, by the device's OS (``platform.system()``; the launcher reports it).
INSTALL_HINTS = {
    "ruff": {"Darwin": "brew install ruff", "": "uv tool install ruff (or pipx install ruff)"},
    "dart": {"Darwin": "brew install --cask flutter", "": "install the Flutter SDK (flutter.dev) and put it on PATH"},
    "flutter": {"Darwin": "brew install --cask flutter", "": "install the Flutter SDK (flutter.dev)"},
    "prettier": {"": "npm install --save-dev prettier"},
    "eslint": {"": "npm install --save-dev eslint @eslint/js typescript-eslint"},
    "gofmt": {"Darwin": "brew install go", "": "install Go (go.dev/dl)"},
    "go": {"Darwin": "brew install go", "": "install Go (go.dev/dl)"},
    "cargo": {"": "install Rust with rustup (rustup.rs), then rustup component add rustfmt clippy"},
    "google-java-format": {"Darwin": "brew install google-java-format", "": "download google-java-format"},
    "checkstyle": {"Darwin": "brew install checkstyle", "": "download the Checkstyle jar (checkstyle.org)"},
    "ktlint": {"Darwin": "brew install ktlint", "": "download ktlint (pinterest.github.io/ktlint)"},
    "detekt": {"Darwin": "brew install detekt", "": "download the detekt CLI (detekt.dev)"},
}


def install_hint(tool: str, os_name: str = "") -> str:
    hints = INSTALL_HINTS.get(tool.rsplit("/", 1)[-1]) or {}
    return hints.get(os_name) or hints.get("") or f"install {tool} in this environment"


def output_levels(output: str, tool: dict[str, Any]) -> set[str] | None:
    """The levels (``tool.levels``: a regex per level over one output line) a failed run's output names; ``None``
    when the tool declares no levels or no line matches one (then the run blocks)."""
    levels = dict(tool.get("levels") or {})
    if not levels:
        return None
    found = {level for level, pattern in levels.items()
             if re.search(str(pattern), output, flags=re.MULTILINE)}
    return found or None


def tool_findings(results: Any, style: dict[str, Any] | None = None) -> list[Finding]:
    """The official formatters' and linters' verdicts the device reports (``style_tools``: ``[{language, kind, tool,
    state, config, output, os}]``, ``state``: ok | failed | missing | timeout). A tool that found problems is red.
    A tool that is not installed is a warning with how to install it (``missing_tool: error``, per
    language or general, makes it red)."""
    found: list[Finding] = []
    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict) or item.get("state") in ("ok", "skipped"):  # skipped: the pipeline runs it
            continue
        kind, tool = str(item.get("kind") or "tool"), str(item.get("tool") or "")
        where = str(item.get("language") or "")
        state = str(item.get("state") or "")
        severity = "error"
        if state == "missing":
            rules = dict(dict(dict(style or {}).get("languages") or {}).get(where) or dict(style or {}).get("general")
                         or {})
            severity = "error" if rules.get("missing_tool") == "error" else "warning"
            hint = install_hint(tool, str(item.get("os") or ""))
            message = f"{kind} {tool or '?'} is not installed ({where}): {hint}"
        elif state == "timeout":
            message = f"{kind} {tool} did not finish in time ({where})"
        else:
            config = "the repository's configuration" if item.get("config") == "repo" else "the platform's defaults"
            output = " ".join(str(item.get("output") or "").split())[:MAX_TOOL_OUTPUT]
            ran = str(item.get("command") or "").strip()
            folder = str(item.get("folder") or ".")
            # Where and how the platform ran it, so the agent runs exactly that.
            how = f" (ran `{ran}` in {folder}/)" if ran else ""
            message = f"{tool} found problems ({where}, {config}){how}: {output}"
            rules = dict(dict(dict(style or {}).get("languages") or {}).get(where) or dict(style or {}).get("general")
                         or {})
            tool_rules = dict(rules.get(kind) or {})
            named = output_levels(str(item.get("output") or ""), tool_rules)
            if named is not None and not named & set(tool_rules.get("blocking") or []) \
                    and len(str(item.get("output") or "")) < MAX_DEVICE_OUTPUT:
                # Only non-blocking levels (an info, a hint): a note in the report, never red (a deprecation info
                # in a framework file must not make every new file red). A cut output may hide a
                # blocking line further up: it stays red.
                severity = "warning"
                message = f"{tool} notes only ({', '.join(sorted(named))}; {where}, {config}): {output}"
            if item.get("old_debt") is True:
                # Only lines the change did not add / files that were so before; warn, as for
                # files and functions already over their limit.
                severity = "warning"
                message = (f"{tool} found problems the files already had before this change ({where}, {config}): "
                           f"{output}")
        found.append(Finding(kind, where or tool, message, severity=severity))
    return found
