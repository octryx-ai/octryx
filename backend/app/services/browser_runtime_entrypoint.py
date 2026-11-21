"""Persistent browser worker entrypoint for Playwright-based automation."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from app.exceptions.contract import build_error_response, with_error_contract
from app.services.browser_runtime_policy import (
    BROWSER_CHROMIUM_LAUNCH_ARGS,
    DEFAULT_BROWSER_INTERACTION_TIMEOUT_MS,
    DEFAULT_BROWSER_NAVIGATION_TIMEOUT_MS,
    DEFAULT_BROWSER_SNAPSHOT_TEXT_PREVIEW_CHARS,
    build_browser_context_kwargs,
    clamp_browser_snapshot_elements,
    clamp_browser_timeout_ms,
    normalize_browser_wait_until,
)
from app.services.browser_runtime_snapshot_script import SNAPSHOT_ELEMENTS_SCRIPT
from app.services.error_facts import error_type


def _ensure_within_workspace(path: str, workspace_root: Path) -> Path:
    candidate = (workspace_root / path).resolve()
    if candidate != workspace_root and workspace_root not in candidate.parents:
        raise with_error_contract(
            ValueError(f"path must stay inside workspace root: {path}"),
            error_code="browser_path_out_of_bounds",
            retryable=False,
        )
    return candidate


class BrowserWorker:
    def __init__(self) -> None:
        self.workspace_root = Path.cwd().resolve()
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._context: Any | None = None
        self._page: Any | None = None

    async def _ensure_page(self, *, user_agent: str | None = None) -> Any:
        if self._page is not None:
            return self._page
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - depends on env
            raise with_error_contract(
                RuntimeError(
                    f"Playwright is not installed in the execution runtime (error_type={error_type(exc)})"
                ),
                error_code="browser_runtime_unavailable",
                retryable=False,
            ) from exc

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=list(BROWSER_CHROMIUM_LAUNCH_ARGS),
        )
        context_kwargs = build_browser_context_kwargs(user_agent)
        self._context = await self._browser.new_context(**context_kwargs)
        self._page = await self._context.new_page()
        return self._page

    async def _snapshot(self, max_elements: int) -> dict[str, Any]:
        if self._page is None:
            raise with_error_contract(
                RuntimeError("No browser page is open"),
                error_code="browser_session_unavailable",
                retryable=True,
            )
        elements = await self._page.evaluate(
            SNAPSHOT_ELEMENTS_SCRIPT,
            max_elements,
            DEFAULT_BROWSER_SNAPSHOT_TEXT_PREVIEW_CHARS,
        )
        return {
            "url": self._page.url,
            "title": await self._page.title(),
            "element_count": len(elements),
            "elements": elements,
        }


    async def handle(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "open_url":
            return await self._open_url(params)
        if action == "snapshot":
            max_elements = clamp_browser_snapshot_elements(params.get("max_elements"))
            return await self._snapshot(max_elements=max_elements)
        if action == "click":
            return await self._click(params)
        if action == "type":
            return await self._type(params)
        if action == "press":
            return await self._press(params)
        if action == "screenshot":
            return await self._screenshot(params)
        if action == "close":
            await self.aclose()
            return {"closed": True}
        raise with_error_contract(
            ValueError(f"Unsupported browser action: {action}"),
            error_code="browser_unsupported_action",
            retryable=False,
        )

    def _require_page(self) -> Any:
        if self._page is None:
            raise with_error_contract(
                RuntimeError("No browser page is open"),
                error_code="browser_session_unavailable",
                retryable=True,
            )
        return self._page

    @staticmethod
    def _required_text(params: dict[str, Any], name: str) -> str:
        value = str(params.get(name) or "").strip()
        if not value:
            raise with_error_contract(
                ValueError(f"{name} is required"),
                error_code="browser_invalid_argument",
                retryable=False,
            )
        return value

    async def _open_url(self, params: dict[str, Any]) -> dict[str, Any]:
        page = await self._ensure_page(user_agent=str(params.get("user_agent") or "").strip() or None)
        timeout_ms = clamp_browser_timeout_ms(
            params.get("timeout_ms"),
            default_ms=DEFAULT_BROWSER_NAVIGATION_TIMEOUT_MS,
        )
        wait_until = normalize_browser_wait_until(params.get("wait_until"))
        url = self._required_text(params, "url")
        await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        return {
            "url": page.url,
            "title": await page.title(),
            "opened": True,
        }

    async def _click(self, params: dict[str, Any]) -> dict[str, Any]:
        page = self._require_page()
        ref = self._required_text(params, "ref")
        timeout_ms = clamp_browser_timeout_ms(
            params.get("timeout_ms"),
            default_ms=DEFAULT_BROWSER_INTERACTION_TIMEOUT_MS,
        )
        locator = page.locator(f'[data-octryx-ref="{ref}"]')
        await locator.first.click(timeout=timeout_ms)
        return {"clicked": True, "ref": ref, "url": page.url, "title": await page.title()}

    async def _type(self, params: dict[str, Any]) -> dict[str, Any]:
        page = self._require_page()
        ref = self._required_text(params, "ref")
        text = str(params.get("text") or "")
        submit = bool(params.get("submit"))
        locator = page.locator(f'[data-octryx-ref="{ref}"]').first
        tag_name = await locator.evaluate("(el) => el.tagName.toLowerCase()")
        if tag_name in {"input", "textarea", "select"}:
            await locator.fill(text)
        else:
            await locator.click()
            await page.keyboard.type(text)
        if submit:
            await page.keyboard.press("Enter")
        return {"typed": True, "ref": ref, "submitted": submit, "text_length": len(text)}

    async def _press(self, params: dict[str, Any]) -> dict[str, Any]:
        page = self._require_page()
        key = self._required_text(params, "key")
        await page.keyboard.press(key)
        return {"pressed": True, "key": key, "url": page.url}

    async def _screenshot(self, params: dict[str, Any]) -> dict[str, Any]:
        page = self._require_page()
        relative_path = str(params.get("path") or "").strip() or f"output/browser/{os.getpid()}.png"
        file_path = _ensure_within_workspace(relative_path, self.workspace_root)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(file_path), full_page=bool(params.get("full_page", True)))
        return {
            "saved": True,
            "path": str(file_path),
            "relative_path": str(file_path.relative_to(self.workspace_root)),
            "url": page.url,
        }

    async def aclose(self) -> None:
        if self._page is not None:
            try:
                await self._page.close()
            except Exception:
                pass
            self._page = None
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None


async def _run() -> None:
    worker = BrowserWorker()
    loop = asyncio.get_running_loop()
    try:
        while True:
            raw_line = await loop.run_in_executor(None, os.sys.stdin.readline)
            if not raw_line:
                break
            payload: dict[str, Any] | None = None
            try:
                payload = json.loads(raw_line)
                request_id = str(payload.get("id") or "")
                action = str(payload.get("action") or "").strip()
                params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
                result = await worker.handle(action, params)
                response = {"id": request_id, "ok": True, "result": result}
            except Exception as exc:  # pragma: no cover - exercised through service layer
                request_id = str(payload.get("id") or "") if payload else ""
                response = {
                    "id": request_id,
                    "ok": False,
                    "error": build_error_response(exc, request_id=request_id or None),
                }
            os.sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            os.sys.stdout.flush()
    finally:
        await worker.aclose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
