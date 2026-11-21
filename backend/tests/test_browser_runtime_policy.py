from __future__ import annotations

from types import MethodType

import pytest

from app.services.browser_runtime_entrypoint import BrowserWorker
from app.services.browser_runtime_policy import (
    BROWSER_CHROMIUM_LAUNCH_ARGS,
    DEFAULT_BROWSER_INTERACTION_TIMEOUT_MS,
    DEFAULT_BROWSER_NAVIGATION_TIMEOUT_MS,
    DEFAULT_BROWSER_SNAPSHOT_ELEMENTS,
    DEFAULT_BROWSER_SNAPSHOT_TEXT_PREVIEW_CHARS,
    DEFAULT_BROWSER_VIEWPORT_HEIGHT,
    DEFAULT_BROWSER_VIEWPORT_WIDTH,
    DEFAULT_BROWSER_WAIT_UNTIL,
    MAX_BROWSER_ACTION_TIMEOUT_MS,
    MIN_BROWSER_ACTION_TIMEOUT_MS,
    build_browser_context_kwargs,
    clamp_browser_snapshot_elements,
    clamp_browser_timeout_ms,
    normalize_browser_wait_until,
)


class _FakePage:
    def __init__(self) -> None:
        self.goto_calls: list[dict[str, object]] = []
        self.url = "https://example.test"

    async def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        self.goto_calls.append(
            {
                "url": url,
                "wait_until": wait_until,
                "timeout": timeout,
            }
        )

    async def title(self) -> str:
        return "Example"


def test_clamp_browser_timeout_ms_applies_defaults_and_bounds() -> None:
    assert (
        clamp_browser_timeout_ms(None, default_ms=DEFAULT_BROWSER_NAVIGATION_TIMEOUT_MS)
        == DEFAULT_BROWSER_NAVIGATION_TIMEOUT_MS
    )
    assert (
        clamp_browser_timeout_ms("250", default_ms=DEFAULT_BROWSER_NAVIGATION_TIMEOUT_MS)
        == MIN_BROWSER_ACTION_TIMEOUT_MS
    )
    assert (
        clamp_browser_timeout_ms("250000", default_ms=DEFAULT_BROWSER_NAVIGATION_TIMEOUT_MS)
        == MAX_BROWSER_ACTION_TIMEOUT_MS
    )
    assert (
        clamp_browser_timeout_ms("oops", default_ms=DEFAULT_BROWSER_INTERACTION_TIMEOUT_MS)
        == DEFAULT_BROWSER_INTERACTION_TIMEOUT_MS
    )


def test_snapshot_and_wait_until_policy_helpers_normalize_values() -> None:
    assert clamp_browser_snapshot_elements(None) == DEFAULT_BROWSER_SNAPSHOT_ELEMENTS
    assert clamp_browser_snapshot_elements("0") == 1
    assert clamp_browser_snapshot_elements("999") == 200
    assert normalize_browser_wait_until(None) == DEFAULT_BROWSER_WAIT_UNTIL
    assert normalize_browser_wait_until("  networkidle ") == "networkidle"
    assert normalize_browser_wait_until("   ") == DEFAULT_BROWSER_WAIT_UNTIL


def test_browser_context_policy_exposes_shared_runtime_constants() -> None:
    assert BROWSER_CHROMIUM_LAUNCH_ARGS == ("--disable-dev-shm-usage", "--no-sandbox")
    assert build_browser_context_kwargs() == {
        "viewport": {
            "width": DEFAULT_BROWSER_VIEWPORT_WIDTH,
            "height": DEFAULT_BROWSER_VIEWPORT_HEIGHT,
        }
    }
    assert build_browser_context_kwargs("octryx-test-agent") == {
        "viewport": {
            "width": DEFAULT_BROWSER_VIEWPORT_WIDTH,
            "height": DEFAULT_BROWSER_VIEWPORT_HEIGHT,
        },
        "user_agent": "octryx-test-agent",
    }


@pytest.mark.asyncio
async def test_browser_worker_open_url_uses_runtime_policy_defaults() -> None:
    worker = BrowserWorker()
    fake_page = _FakePage()

    async def _fake_ensure_page(self: BrowserWorker, *, user_agent: str | None = None) -> _FakePage:
        assert user_agent is None
        return fake_page

    worker._ensure_page = MethodType(_fake_ensure_page, worker)

    result = await worker.handle(
        "open_url",
        {
            "url": "https://example.test",
            "timeout_ms": "999999",
            "wait_until": "   ",
        },
    )

    assert result["opened"] is True
    assert fake_page.goto_calls == [
        {
            "url": "https://example.test",
            "wait_until": DEFAULT_BROWSER_WAIT_UNTIL,
            "timeout": MAX_BROWSER_ACTION_TIMEOUT_MS,
        }
    ]


@pytest.mark.asyncio
async def test_browser_worker_snapshot_uses_clamped_policy_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = BrowserWorker()
    observed: dict[str, int] = {}

    async def _fake_snapshot(self: BrowserWorker, *, max_elements: int) -> dict[str, object]:
        observed["max_elements"] = max_elements
        return {"elements": [], "element_count": 0, "title": "Example", "url": "https://example.test"}

    monkeypatch.setattr(BrowserWorker, "_snapshot", _fake_snapshot)

    await worker.handle("snapshot", {"max_elements": "999"})

    assert observed["max_elements"] == 200


@pytest.mark.asyncio
async def test_browser_worker_snapshot_uses_shared_preview_length_constant() -> None:
    class _FakeSnapshotPage:
        def __init__(self) -> None:
            self.evaluate_calls: list[tuple[object, ...]] = []
            self.url = "https://example.test/snapshot"

        async def evaluate(self, script: str, max_elements: int, preview_chars: int) -> list[dict[str, str]]:
            self.evaluate_calls.append((script, max_elements, preview_chars))
            return [{"ref": "e1", "text": "Example"}]

        async def title(self) -> str:
            return "Snapshot"

    worker = BrowserWorker()
    worker._page = _FakeSnapshotPage()

    result = await worker._snapshot(max_elements=7)

    assert result["element_count"] == 1
    assert worker._page.evaluate_calls[0][1:] == (7, DEFAULT_BROWSER_SNAPSHOT_TEXT_PREVIEW_CHARS)
