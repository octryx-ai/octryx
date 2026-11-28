"""Pixel-faithful Office rendering (PDF/PNG) with LibreOffice — only where it cannot reach a network."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from . import render_sandbox as sandbox
from .render_sandbox import (
    MAX_RENDER_BYTES,
    OFFICE_PREVIEW_UNAVAILABLE,
    OFFICE_RENDER_BUSY,
    OFFICE_RENDER_FAILED,
    OFFICE_RENDER_TOO_LARGE,
    OFFICE_RENDER_UNSUPPORTED,
    RenderError,
)

SOCKET_ENV = "OCTRYX_OFFICE_RENDER_SOCKET"
SIDECAR_TIMEOUT_SEC = 150
MAX_RESULT_BYTES = 128 * 1024 * 1024


class OfficePreviewUnavailableError(RuntimeError):
    code = OFFICE_PREVIEW_UNAVAILABLE

    def __init__(self) -> None:
        super().__init__(OFFICE_PREVIEW_UNAVAILABLE)


class OfficeRenderError(RuntimeError):
    def __init__(self, code: str = OFFICE_RENDER_FAILED, fact: str = "") -> None:
        super().__init__(f"{code} {fact}".strip())
        self.code = code


def _raise(exc: RenderError) -> None:
    if exc.code == OFFICE_PREVIEW_UNAVAILABLE:
        raise OfficePreviewUnavailableError() from exc
    raise OfficeRenderError(exc.code, str(exc).removeprefix(exc.code).strip()) from exc


async def _render_via_sidecar(socket_path: str, data: bytes, suffix: str, fmt: str) -> bytes:
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
    except OSError as exc:
        raise RenderError(OFFICE_PREVIEW_UNAVAILABLE) from exc
    try:
        writer.write(json.dumps({"format": fmt, "suffix": suffix, "size": len(data)}).encode() + b"\n" + data)
        await writer.drain()
        header = json.loads(await asyncio.wait_for(reader.readline(), timeout=SIDECAR_TIMEOUT_SEC))
        if not header.get("ok"):
            raise RenderError(str(header.get("code") or OFFICE_RENDER_FAILED))
        size = int(header.get("size") or 0)
        if size > MAX_RESULT_BYTES:
            raise RenderError(OFFICE_RENDER_FAILED, "result too large")
        return await asyncio.wait_for(reader.readexactly(size), timeout=SIDECAR_TIMEOUT_SEC)
    except (TimeoutError, ValueError, asyncio.IncompleteReadError) as exc:
        raise RenderError(OFFICE_RENDER_FAILED, type(exc).__name__) from exc
    finally:
        writer.close()


async def render_office_document(path: str | Path, fmt: str = "pdf") -> bytes:
    source = Path(path)
    try:
        sandbox.check_request(source.suffix, source.stat().st_size, fmt)
        data = source.read_bytes()
        socket_path = os.environ.get(SOCKET_ENV, "").strip()
        if socket_path:
            return await _render_via_sidecar(socket_path, data, source.suffix.lower(), fmt)
        return await sandbox.convert(data, source.suffix, fmt)
    except RenderError as exc:
        _raise(exc)
        raise  # unreachable: _raise always raises


_STATE_TEXT = {
    OFFICE_PREVIEW_UNAVAILABLE: (
        "Rendered preview unavailable",
        "No network-isolated renderer is available where the platform runs, so the exact layout is not rendered. "
        "The document preview and the inspector tabs still show the content.",
    ),
    OFFICE_RENDER_BUSY: ("Renderer busy", "Too many documents are being rendered right now. Try again shortly."),
    OFFICE_RENDER_TOO_LARGE: (
        "Document too large to render",
        f"Documents above {MAX_RENDER_BYTES // (1024 * 1024)} MB are not rendered.",
    ),
    OFFICE_RENDER_UNSUPPORTED: ("Not rendered", "Only .docx, .xlsx and .pptx documents are rendered."),
    OFFICE_RENDER_FAILED: (
        "Rendering failed",
        "The document could not be rendered. Validate it with the Office tools to find the cause.",
    ),
}
STATE_STATUS = {
    OFFICE_PREVIEW_UNAVAILABLE: 503,
    OFFICE_RENDER_BUSY: 503,
    OFFICE_RENDER_TOO_LARGE: 413,
    OFFICE_RENDER_UNSUPPORTED: 415,
    OFFICE_RENDER_FAILED: 422,
}


def render_state_page(code: str) -> str:
    title, text = _STATE_TEXT.get(code, _STATE_TEXT[OFFICE_RENDER_FAILED])
    return (
        '<!doctype html><html><head><meta charset="utf-8"><title>'
        f"{title}</title></head><body style=\"font-family:sans-serif;max-width:640px;margin:48px auto\">"
        f"<h1 style=\"font-size:20px\">{title}</h1><p>{text}</p><p><code>{code}</code></p></body></html>"
    )


async def render_check(path: str | Path) -> dict[str, Any]:
    try:
        pdf = await render_office_document(path, "pdf")
    except OfficePreviewUnavailableError:
        return {"status": OFFICE_PREVIEW_UNAVAILABLE}
    except OfficeRenderError as exc:
        return {"status": exc.code}
    return {"status": "rendered", "format": "pdf", "pages": len(re.findall(rb"/Type\s*/Page[^s]", pdf)), "bytes": len(pdf)}


__all__ = [
    "SOCKET_ENV",
    "STATE_STATUS",
    "OfficePreviewUnavailableError",
    "OfficeRenderError",
    "render_check",
    "render_office_document",
    "render_state_page",
]
