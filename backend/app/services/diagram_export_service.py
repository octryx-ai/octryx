"""Server-side draw.io diagram rendering (PNG) via the local drawio CLI.

The platform stores diagrams as draw.io XML (``<mxGraphModel>`` documents
produced by the diagram tools). This service renders them into pixel-accurate
PNGs using the installed draw.io desktop CLI (``drawio -x -f png``).

Explicit states, no silent fallback:

- Binary not installed/resolvable -> :class:`DiagramRendererUnavailableError`
  (state ``renderer_unavailable``). Callers degrade explicitly (the chat card
  falls back to the interactive embed, the endpoint answers 503).
- CLI failure, invalid XML, timeout, or non-PNG output ->
  :class:`DiagramRenderError` with the CLI detail.

Rendered PNGs are cached on disk per ``diagram_id`` + content hash + scale so
repeated chat views never re-launch the Electron export. The cache is bounded
by a simple LRU file cleanup.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from .error_facts import error_type

logger = logging.getLogger(__name__)

DRAWIO_BIN_ENV = "OCTRYX_DRAWIO_BIN"
DIAGRAM_PNG_CACHE_DIR_ENV = "OCTRYX_DIAGRAM_PNG_CACHE_DIR"

_DEFAULT_DRAWIO_BIN = "drawio"
_DEFAULT_CACHE_DIR = "var/cache/diagram_png"

RENDER_TIMEOUT_SECONDS = 60
ALLOWED_SCALES = (1, 2)
_CACHE_MAX_FILES = 200
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# draw.io desktop is an Electron app; concurrent headless exports compete for
# the same app instance. Serialize renders process-wide.
_RENDER_LOCK = threading.Lock()


class DiagramRendererUnavailableError(RuntimeError):
    """Explicit ``renderer_unavailable`` state: no drawio CLI binary."""


class DiagramRenderError(RuntimeError):
    """The drawio CLI failed to produce a valid PNG for the given XML."""


def resolve_drawio_binary() -> str | None:
    """Return the drawio executable path, or ``None`` when unavailable."""
    configured = str(os.environ.get(DRAWIO_BIN_ENV) or "").strip() or _DEFAULT_DRAWIO_BIN
    return shutil.which(configured)


def renderer_available() -> bool:
    return resolve_drawio_binary() is not None


def _cache_dir() -> Path:
    configured = str(os.environ.get(DIAGRAM_PNG_CACHE_DIR_ENV) or "").strip()
    return Path(configured or _DEFAULT_CACHE_DIR)


def _safe_cache_stem(diagram_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", str(diagram_id or ""))[:48]
    return cleaned or "diagram"


def diagram_png_cache_path(*, diagram_id: str, diagram_xml: str, scale: int) -> Path:
    """Deterministic cache location for one diagram content + scale."""
    content_sha = hashlib.sha256(diagram_xml.encode("utf-8")).hexdigest()[:24]
    name = f"{_safe_cache_stem(diagram_id)}-{content_sha}-s{scale}.png"
    return _cache_dir() / name


def render_diagram_png(*, diagram_id: str, diagram_xml: str, scale: int = 2) -> bytes:
    """Render draw.io XML to PNG bytes, serving from the disk cache when possible.

    Raises :class:`DiagramRendererUnavailableError` when the drawio CLI is not
    installed and :class:`DiagramRenderError` on any render failure.
    """
    if scale not in ALLOWED_SCALES:
        raise DiagramRenderError(f"Unsupported scale {scale!r}; allowed: {ALLOWED_SCALES}")
    xml = str(diagram_xml or "").strip()
    if "<mxGraphModel" not in xml and "<mxfile" not in xml:
        raise DiagramRenderError("Diagram XML must contain an <mxGraphModel> or <mxfile> document")

    cache_path = diagram_png_cache_path(diagram_id=diagram_id, diagram_xml=xml, scale=scale)
    cached = _read_cached_png(cache_path)
    if cached is not None:
        return cached

    binary = resolve_drawio_binary()
    if binary is None:
        raise DiagramRendererUnavailableError(
            "renderer_unavailable: drawio CLI not found "
            f"(set {DRAWIO_BIN_ENV} or install draw.io desktop with the CLI on PATH)"
        )

    with _RENDER_LOCK:
        # Re-check under the lock: a concurrent request may have rendered it.
        cached = _read_cached_png(cache_path)
        if cached is not None:
            return cached
        png = _run_drawio_export(binary, xml, scale)

    _write_cache(cache_path, png)
    return png


def _read_cached_png(cache_path: Path) -> bytes | None:
    try:
        data = cache_path.read_bytes()
    except OSError:
        return None
    if not data.startswith(_PNG_MAGIC):
        return None
    try:
        cache_path.touch()  # LRU signal for the cleanup
    except OSError:
        pass
    return data


def _run_drawio_export(binary: str, xml: str, scale: int) -> bytes:
    with tempfile.TemporaryDirectory(prefix="octryx-diagram-export-") as tmp_dir:
        source = Path(tmp_dir) / "diagram.drawio"
        target = Path(tmp_dir) / "diagram.png"
        source.write_text(xml, encoding="utf-8")
        # White background (no --transparent) with a small border margin so the
        # preview stays readable on both light and dark chat themes.
        command = [
            binary,
            "-x",
            "-f",
            "png",
            "-s",
            str(scale),
            "-b",
            "8",
            "-o",
            str(target),
            str(source),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=RENDER_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DiagramRenderError(
                f"drawio export timed out after {RENDER_TIMEOUT_SECONDS}s"
            ) from exc
        except OSError as exc:
            raise DiagramRenderError(
                f"drawio CLI could not be executed (error_type={error_type(exc)})"
            ) from exc
        if completed.returncode != 0:
            # The CLI's output (Electron/X11 noise, source paths) is never carried: exit status only.
            raise DiagramRenderError(f"drawio_export_failed exit_code={completed.returncode}")
        try:
            png = target.read_bytes()
        except OSError as exc:
            raise DiagramRenderError("drawio export produced no output file") from exc
    if not png.startswith(_PNG_MAGIC):
        raise DiagramRenderError("drawio export produced a non-PNG output file")
    return png


def _write_cache(cache_path: Path, png: bytes) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_suffix(".tmp")
        tmp_path.write_bytes(png)
        tmp_path.replace(cache_path)
    except OSError:
        logger.warning("diagram_export.cache_write_failed", extra={"path": str(cache_path)})
        return
    _prune_cache(cache_path.parent)


def _prune_cache(directory: Path) -> None:
    """Bounded cache: keep the newest ``_CACHE_MAX_FILES`` PNGs (LRU by mtime)."""
    try:
        entries = [(path.stat().st_mtime, path) for path in directory.glob("*.png")]
    except OSError:
        return
    if len(entries) <= _CACHE_MAX_FILES:
        return
    entries.sort(reverse=True)
    for _, stale in entries[_CACHE_MAX_FILES:]:
        try:
            stale.unlink()
        except OSError:
            pass


__all__ = [
    "ALLOWED_SCALES",
    "DIAGRAM_PNG_CACHE_DIR_ENV",
    "DRAWIO_BIN_ENV",
    "DiagramRenderError",
    "DiagramRendererUnavailableError",
    "diagram_png_cache_path",
    "render_diagram_png",
    "renderer_available",
    "resolve_drawio_binary",
]
