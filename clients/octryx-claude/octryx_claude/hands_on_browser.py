"""The hands-on scenarios in a real browser (``hands_on``): Playwright on the device's installed Google Chrome
(``channel="chrome"``, never a download), one persistent profile per scenario so a reload or a restart keeps what the
app stored (IndexedDB, localStorage, OPFS). A Flutter web app draws on a canvas: its texts are read from its
accessibility tree, which the runner switches on after every load.

A missing Playwright or Chrome raises :class:`BrowserUnavailableError` with how to install it; the device never
installs.
"""

from __future__ import annotations

import contextlib
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .hands_on_page import (
    TIMEOUT_MS,
    StepFailedError,
    _fill,
    _in_fields,
    _point,
    _reach,
    _semantics,
)

ABSENT_MS = 2_500
PLAYWRIGHT_HINT = ("Playwright is missing in the launcher's Python: install it there (`pip install playwright`); the "
                   "test uses the installed Google Chrome, so no browser download is needed.")
START_SECONDS = 60  # the platform's data (general.browser_start_seconds) overrides it
# Before a restart: network idle (at most this long), then time for the app's storage writes (general.restart_settle).
SETTLE = {"network_idle_seconds": 5, "storage_ms": 1000}
START_HINT = ("The browser did not start within {seconds} s: is a Chrome update running (GoogleUpdater)? Try again "
              "when it is done, or set \"browser\": \"chromium\" in the environment file to use Playwright's own "
              "Chromium (`playwright install chromium`), which no system update touches.")
CHROME_HINT = ("Google Chrome is not installed on this device: install Chrome, or set \"browser\": \"chromium\" in the "
               "environment file and run `playwright install chromium` yourself (the launcher never downloads).")



class BrowserUnavailableError(Exception):
    def __init__(self, hint: str) -> None:
        super().__init__(hint)
        self.hint = hint


class Session:
    """One scenario's browser on its own profile."""

    def __init__(self, playwright: Any, channel: str | None, viewport: dict[str, int], base_url: str,
                 start_seconds: int = START_SECONDS, settle: dict[str, int] | None = None) -> None:
        self.playwright, self.channel, self.viewport, self.base_url = playwright, channel, viewport, base_url
        self.start_seconds = start_seconds
        self.settle = {**SETTLE, **(settle or {})}
        self.profile = Path(tempfile.mkdtemp(prefix="octryx-hands-on-"))
        self.context: Any = None
        self.page: Any = None
        self.url = base_url

    def open(self) -> None:
        try:
            self.context = self.playwright.chromium.launch_persistent_context(
                str(self.profile), headless=True, viewport=self.viewport, timeout=self.start_seconds * 1000,
                **({"channel": self.channel} if self.channel else {}))
        except Exception as error:  # noqa: BLE001 - which browser is missing decides the hint
            text = str(error)
            if type(error).__name__ == "TimeoutError" or "Timeout" in text.split("\n")[0]:
                # While the GoogleUpdater ran no Chrome started; the run waited for its command's
                # timeout. A short start limit says so at once (browser_unavailable, cause environment).
                raise BrowserUnavailableError(START_HINT.format(seconds=self.start_seconds)) from None
            if "chrome" in text.lower() or "Executable doesn't exist" in text or "distribution" in text.lower():
                raise BrowserUnavailableError(CHROME_HINT) from None
            raise
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

    def close(self) -> None:
        if self.context is not None:
            try:
                self.context.close()
            except Exception:  # noqa: BLE001 - closing a dead browser
                pass
            self.context = None

    def settle_before_close(self) -> None:
        """Let the app finish what the last step started before the browser closes (closing
        right after a click lost a bean written to localStorage, so a scenario about surviving a restart was red)."""
        idle, storage = int(self.settle["network_idle_seconds"]), int(self.settle["storage_ms"])
        if self.page is None:
            return
        if idle > 0:  # Playwright's timeout 0 means no limit
            with contextlib.suppress(Exception):  # an app that never goes idle (polling, a socket) waits the cap only
                self.page.wait_for_load_state("networkidle", timeout=idle * 1000)
        if storage > 0:
            with contextlib.suppress(Exception):
                self.page.wait_for_timeout(storage)

    def discard(self) -> None:
        self.close()
        shutil.rmtree(self.profile, ignore_errors=True)

    def step(self, step: dict[str, Any], shots: Path, prefix: str) -> str | None:
        """Run one step; the screenshot's file name when it took one."""
        op, page = step["do"], self.page
        if op == "goto":
            self.url = self.base_url.rstrip("/") + step["path"]
            page.goto(self.url, timeout=TIMEOUT_MS * 4)
            _semantics(page)
        elif op == "reload":
            page.reload(timeout=TIMEOUT_MS * 4)
            _semantics(page)
        elif op == "restart":
            self.url = page.url or self.url
            self.settle_before_close()
            self.close()
            self.open()
            self.page.goto(self.url, timeout=TIMEOUT_MS * 4)
            _semantics(self.page)
        elif op == "click":
            point = _reach(page, step["text"])
            if point is None:
                raise StepFailedError(f"nothing visible shows {step['text']!r}")
            page.mouse.click(point["x"], point["y"])
            page.wait_for_timeout(300)
        elif op == "fill":
            _fill(page, step["label"], step["value"])
        elif op == "press":
            page.keyboard.press(step["key"])
        elif op == "wait":
            page.wait_for_timeout(step["ms"])
        elif op == "expect_text":
            if _point(page, step["text"]) is None and not _in_fields(page, step["text"]):
                raise StepFailedError(f"{step['text']!r} is not shown")
        elif op == "expect_no_text":
            page.wait_for_timeout(ABSENT_MS)
            if _point(page, step["text"], timeout_ms=0) is not None or _in_fields(page, step["text"]):
                raise StepFailedError(f"{step['text']!r} is shown but must not be")
        elif op == "screenshot":
            return self.shot(shots, f"{prefix}-{step['name']}")
        return None

    def shot(self, shots: Path, name: str) -> str | None:
        target = shots / f"{name}.png"
        try:
            self.page.screenshot(path=str(target), full_page=True)
        except Exception:  # noqa: BLE001 - a screenshot is evidence, never the verdict
            return None
        return target.name


EXPECT_OPS = ("expect_text", "expect_no_text")


PASSIVE_OPS = ("screenshot", "wait")


def symptom_steps(steps: list[dict[str, Any]]) -> list[int]:
    """The steps that show a bug's symptom: those marked ``"symptom": true``, else the closing expect steps (every
    expect after the scenario's last action; the reproduce phase writes the correct behaviour there). Live
    : 's scenario failed while it still added its grinder and counted as reproduced; 's
    symptom showed at the first of its two closing expects ("No grinder yet" after the reload)."""
    marked = [index for index, step in enumerate(steps) if step.get("symptom") is True]
    if marked:
        return marked
    actions = [index for index, step in enumerate(steps) if step.get("do") not in (*EXPECT_OPS, *PASSIVE_OPS)]
    after = actions[-1] if actions else -1
    return [index for index, step in enumerate(steps) if index > after and step.get("do") in EXPECT_OPS]


def run_scenario(playwright: Any, channel: str | None, scenario: dict[str, Any], base_url: str,
                 shots: Path, start_seconds: int = START_SECONDS,
                 settle: dict[str, int] | None = None) -> dict[str, Any]:
    """``{id, passed, failed_step, error, screenshots}`` of one scenario; a missing browser propagates."""
    # A repository scenario's id is a path (repo:tests/hands_on/bugs/.json#1): one flat file name, else the
    # screenshot lands in subfolders and its upload (by name) never finds it.
    prefix = "hands-on-" + re.sub(r"[^a-z0-9._#-]+", "_", scenario["id"].lower())
    session = Session(playwright, channel, scenario["viewport"], base_url, start_seconds, settle)
    taken: list[str] = []
    steps = list(scenario.get("seed") or [])
    restart_at = len(steps)  # with existing data: the seed, a restart, then the scenario
    steps += list(scenario["steps"])
    index = -1
    try:
        session.open()
        if not steps or steps[0]["do"] != "goto":
            session.step({"do": "goto", "path": "/"}, shots, prefix)
        for index, step in enumerate(steps):
            if index == restart_at and restart_at:
                session.step({"do": "restart"}, shots, prefix)
            if (name := session.step(step, shots, prefix)) is not None:
                taken.append(name)
        if (name := session.shot(shots, f"{prefix}-end")) is not None:
            taken.append(name)
        return {"id": scenario["id"], "passed": True, "screenshots": taken}
    except BrowserUnavailableError:
        raise
    except Exception as error:  # noqa: BLE001 - a failed step is the scenario's result
        if session.page is not None and (name := session.shot(shots, f"{prefix}-failed")) is not None:
            taken.append(name)
        failed_op = steps[index]["do"] if 0 <= index < len(steps) else "goto"
        symptom = symptom_steps(steps)
        return {"id": scenario["id"], "passed": False, "failed_step": max(index, 0), "failed_op": failed_op,
                "failed_symptom": index in symptom, "symptom_step": symptom[0] if symptom else -1,
                "error": str(error).splitlines()[0][:400] if str(error) else type(error).__name__,
                "screenshots": taken}
    finally:
        session.discard()


__all__ = ["BrowserUnavailableError", "CHROME_HINT", "PLAYWRIGHT_HINT", "run_scenario"]
