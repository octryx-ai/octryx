"""The pytest plugin the launcher puts into every test run on a device (``PYTEST_PLUGINS=octryx_pytest``).

It is copied next to nothing else into a folder outside the launcher's state (``browser.plugin_dir``), because the
repository's own interpreter loads it and that interpreter has no octryx-claude installed. It depends on nothing but
pytest, and on Playwright only when the repository has it. Without its environment variables it does nothing.

1. **The device's Google Chrome for Playwright** (simply use the Chrome already installed
   instead of a browser download per device). With ``OCTRYX_BROWSER_CHANNEL`` set (the launcher sets ``chrome`` when
   Google Chrome is
   installed and the repository does not ask for the bundled browser), a Chromium launch that names no ``channel``
   and no ``executable_path`` gets that channel: ``p.chromium.launch()`` in a conftest and pytest-playwright's
   ``page`` fixture alike. Nothing is downloaded per repository or worktree; the agent needs no special knowledge.
   Agent-written conftests call ``pw.chromium.launch()`` directly, which an option of pytest-playwright alone
   would not reach.
   With ``OCTRYX_BROWSER_MISSING`` set (no Chrome on the device, no bundled browser asked for), a failed launch says
   what to do instead of Playwright's "Executable doesn't exist".
2. **Failed tests of a run, and a re-run of just those** (the pipeline's flaky-test re-run): with
   ``OCTRYX_PYTEST_FAILED_FILE`` the node ids of every failed or erroring test are written there at the end; with
   ``OCTRYX_PYTEST_ONLY_FILE`` only the node ids listed there run. It works whatever the declared command looks like
   (``cd app && pytest``, ``make test``) and also without pytest's cache (``-p no:cacheprovider``), unlike ``--lf``.
"""

from __future__ import annotations

import os
from pathlib import Path

CHANNEL_ENV = "OCTRYX_BROWSER_CHANNEL"
MISSING_ENV = "OCTRYX_BROWSER_MISSING"
FAILED_ENV = "OCTRYX_PYTEST_FAILED_FILE"
ONLY_ENV = "OCTRYX_PYTEST_ONLY_FILE"
MISSING_MESSAGE = (
    "Google Chrome is not installed on this device, so the system tests have no browser. Install Google Chrome "
    "(https://www.google.com/chrome/), or let the repository use Playwright's bundled browser: set "
    "coding_setup.environment.browser to \"chromium\" and add `playwright install chromium` to its setup."
)
_PATCHED = "_octryx_channel_patched"


def _with_channel(original, channel: str):
    def launch(self, *args, **kwargs):
        if getattr(self, "name", "") == "chromium" and not kwargs.get("channel") and not kwargs.get(
                "executable_path"):
            kwargs["channel"] = channel
        return original(self, *args, **kwargs)

    setattr(launch, _PATCHED, True)
    return launch


def _explaining(original):
    def launch(self, *args, **kwargs):
        try:
            return original(self, *args, **kwargs)
        except Exception as error:  # Playwright's own Error type differs per version
            if "Executable doesn't exist" in str(error):
                raise RuntimeError(MISSING_MESSAGE) from error
            raise

    setattr(launch, _PATCHED, True)
    return launch


def patch_playwright(channel: str, missing: bool) -> bool:
    """Wrap the public ``BrowserType.launch`` and ``launch_persistent_context`` of the sync and async API; ``False``
    when Playwright is not installed (nothing to do)."""
    try:
        from playwright.async_api import BrowserType as AsyncBrowserType
        from playwright.sync_api import BrowserType as SyncBrowserType
    except ImportError:
        return False
    for cls in (SyncBrowserType, AsyncBrowserType):
        for name in ("launch", "launch_persistent_context"):
            original = getattr(cls, name, None)
            if original is None or getattr(original, _PATCHED, False):
                continue
            if channel:
                setattr(cls, name, _with_channel(original, channel))
            elif missing:
                setattr(cls, name, _explaining(original))
    return True


def _only_ids() -> set[str] | None:
    path = os.environ.get(ONLY_ENV, "").strip()
    if not path:
        return None
    try:
        return {line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()}
    except OSError:
        return None


def pytest_configure(config):
    patch_playwright(os.environ.get(CHANNEL_ENV, "").strip(), bool(os.environ.get(MISSING_ENV, "").strip()))


def pytest_collection_modifyitems(config, items):
    wanted = _only_ids()
    if wanted is None:
        return
    keep = [item for item in items if item.nodeid in wanted]
    dropped = [item for item in items if item.nodeid not in wanted]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = keep


_FAILED: list[str] = []


def pytest_sessionstart(session):
    _FAILED.clear()


def pytest_runtest_logreport(report):
    if report.failed and report.nodeid not in _FAILED:
        _FAILED.append(report.nodeid)


def pytest_sessionfinish(session):
    path = os.environ.get(FAILED_ENV, "").strip()
    if not path:
        return
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("".join(f"{nodeid}\n" for nodeid in _FAILED), encoding="utf-8")
    except OSError:
        pass
