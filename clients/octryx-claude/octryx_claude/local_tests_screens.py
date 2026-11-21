"""Screenshots outside the sandbox (``local_tests``) and what a session hears when its browser could not start
inside it. Stdlib only.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
from typing import Any
from urllib.parse import urlsplit

from .local_tests_words import _PYTHON, _inside, unwrap

# A screenshot of the app the session started, by Playwright's own CLI: the run note tells the session to look at
# each screen at 1280 and 390 px, and Chromium cannot start inside the sandbox (the same mach-register refusal as the
# system tests). Only
# ``<python> -m playwright screenshot`` / ``[npx] playwright screenshot`` with its own options, a loopback URL
# (127.0.0.1, localhost, [::1]) and an output file inside the repository: it opens that one page and writes one image.
_LOOPBACK_URL = re.compile(r"^https?://(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+)?(?:[/?#]\S*)?$")
_SCREENSHOT_VALUE_OPTIONS = frozenset({"-b", "--browser", "--channel", "--color-scheme", "--device", "--geolocation",
                                       "--lang", "--timezone", "--user-agent", "--viewport-size",
                                       "--wait-for-selector", "--wait-for-timeout", "--timeout"})
_SCREENSHOT_REFUSED_OPTIONS = frozenset({"--proxy-server", "--proxy-bypass", "--load-storage", "--save-storage",
                                         "--save-har", "--save-har-glob", "--user-data-dir", "--ignore-https-errors"})


def screenshot(words: list[str], root: str = "") -> bool:
    """A Playwright CLI screenshot of a loopback page into the repository (comment above)."""
    name = posixpath.basename(words[0]) if words else ""
    if name == "npx":
        words = words[1:]
        name = posixpath.basename(words[0]) if words else ""
    if name == "playwright":
        rest = words[1:]
    elif _PYTHON.match(name) and words[1:3] == ["-m", "playwright"]:
        rest = words[3:]
    else:
        return False
    if not rest or rest[0] != "screenshot":
        return False
    positional: list[str] = []
    args = rest[1:]
    index = 0
    while index < len(args):
        arg = args[index]
        option = arg.split("=", 1)[0]
        if option in _SCREENSHOT_REFUSED_OPTIONS:
            return False
        if arg.startswith("-"):
            index += 2 if option in _SCREENSHOT_VALUE_OPTIONS and "=" not in arg else 1
            continue
        positional.append(arg)
        index += 1
    return (len(positional) == 2 and bool(_LOOPBACK_URL.match(positional[0])) and not _platform_page(positional[0])
            and _inside(positional[1], root) and not positional[1].startswith("-"))


# The platform itself may listen on loopback (a local stack, ``OCTRYX_BASE_URL=http://127.0.0.1:24600``); a screenshot
# outside the sandbox looks only at the session's own app, never at the platform's port.
PLATFORM_URL_ENV = "OCTRYX_BASE_URL"
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _port(url: str) -> int | None:
    parts = urlsplit(url)
    try:
        return parts.port or _DEFAULT_PORTS.get(parts.scheme)
    except ValueError:
        return None


def _platform_page(url: str) -> bool:
    """``url`` is on the platform's port while the platform listens on loopback."""
    platform = str(os.environ.get(PLATFORM_URL_ENV) or "").strip()
    if not platform or not _LOOPBACK_URL.match(platform.rstrip("/") + "/"):
        return False
    return _port(url) == _port(platform)


# A session's own Playwright script (``python -I shots.py``) is no test run, so it runs inside the sandbox, where
# Chromium fails with the mach-register refusal every time. Waiting cannot change the sandbox. The session hears what
# can run instead (the Playwright CLI form above, wrapped like a
# test run) or that it may skip the visual check.
# The fallback of the catalog's ``run.launcher.sandbox_browser`` (same words; the contract's ``prompt_texts`` win).
SANDBOX_BROWSER_KEY = "run.launcher.sandbox_browser"
SANDBOX_BROWSER_MESSAGE = (
    "This cannot run here: Chromium cannot start inside this sandbox, and waiting or retrying does not change that, "
    "so do not schedule a wakeup for it. Next: take a screenshot with `python -m playwright screenshot "
    "--viewport-size 1280,800 http://127.0.0.1:<port>/ <file inside the repository>` (it runs outside the sandbox, "
    "loopback URLs only; start the app first), or skip the visual check and note it in your summary.")


def sandbox_browser_text(contract: dict[str, Any] | None) -> str:
    """The catalog's text for a browser that cannot start in the sandbox (two of three
    paths sent this module's own copy, so a Workspace's override reached only one)."""
    texts = contract.get("prompt_texts") if isinstance(contract, dict) else None
    found = texts.get(SANDBOX_BROWSER_KEY) if isinstance(texts, dict) else None
    return str(found) if isinstance(found, str) and found.strip() else SANDBOX_BROWSER_MESSAGE
_SANDBOX_CHROMIUM = re.compile(r"MachPortRendezvousServer|BrowserType\.launch\b.*?(?:Permission denied|kill EPERM|"
                               r"ProcessSingleton|has been closed)", re.DOTALL)


def sandbox_browser_failure(hook_input: dict[str, Any]) -> bool:
    """A Bash call that ran inside the sandbox (not the test-run wrapper) and whose browser could not start there."""
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    if hook_input.get("tool_name") != "Bash" or unwrap(str(tool_input.get("command") or "")) is not None:
        return False
    # PostToolUse carries ``tool_response``; a command that exited non-zero comes as PostToolUseFailure's ``error``.
    output = [hook_input.get("tool_response"), hook_input.get("error")]
    text = "\n".join(part if isinstance(part, str) else json.dumps(part, default=str) for part in output if part)
    return bool(_SANDBOX_CHROMIUM.search(text))


def sandbox_tool_failure(hook_input: dict[str, Any], tools: list[tuple[list[str], bool]] | None) -> str | None:
    """The style tool that could not run inside the sandbox ("Operation not permitted" in its output), or ``None``.
    The session hears it even when it filtered that line away (silence is no clean format)."""
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    command = " " + " ".join(str(tool_input.get("command") or "").split()) + " "
    if hook_input.get("tool_name") != "Bash" or unwrap(command.strip()) is not None:
        return None
    output = [hook_input.get("tool_response"), hook_input.get("error")]
    text = "\n".join(part if isinstance(part, str) else json.dumps(part, default=str) for part in output if part)
    found = next((" ".join(prefix) for prefix, outside in tools or []
                  if outside and f" {' '.join(prefix)} " in command), None)
    return found if found and "Operation not permitted" in text else None
