"""The SPA's static mounts: content-hashed bundles cached for a year, text files served gzip-compressed.

The chat/admin frontend build (``frontend/chat/vite.config.ts``) writes every chunk to ``chat/assets/`` under a
name that carries its content hash (``vendor-D9lvy8W_.js``). Such a file never changes under its name, so it is
served with ``Cache-Control: public, max-age=31536000, immutable``; a deploy ships new names, and the page shell
that names them (``/chat``, ``index.html``) is answered ``no-store`` by its own route, so a deploy takes effect on
the next load. Every other file in the mount (favicon, logos, the fixed-name scripts) is revalidated through
``ETag`` / ``Last-Modified``.

A compressible file (JS, CSS, JSON, SVG, HTML, WASM) of at least 1 KiB is compressed once per process and kept in
memory (bounded, keyed by path, size and mtime), and
answered with ``Content-Encoding: gzip`` when the client accepts it. A ``Range`` request, a ``HEAD`` request and a
client without gzip get the file itself; conditional requests answer ``304``.
"""

from __future__ import annotations

import os
import re
from collections import OrderedDict
from pathlib import Path

import anyio
from starlette.datastructures import Headers
from starlette.responses import FileResponse, Response
from starlette.staticfiles import NotModifiedResponse, StaticFiles
from starlette.types import Scope

from ..middleware.transport.compression import (
    MINIMUM_SIZE,
    accepts_gzip,
    gzip_bytes,
    is_compressible_media_type,
    weak_etag,
)

IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"
#: The build's chunk directory, relative to the static mount, and its file names: ``<name>-<8 char hash>.<ext>``.
HASHED_ASSET_DIR = ("chat", "assets")
_HASHED_NAME = re.compile(r"-[A-Za-z0-9_-]{8}\.[A-Za-z0-9]+$")
#: Files larger than this are served uncompressed (nothing the build emits comes close).
MAX_COMPRESSED_SOURCE_BYTES = 32 * 1024 * 1024
#: Total compressed bytes kept per process; least recently used entries leave first.
CACHE_BUDGET_BYTES = 64 * 1024 * 1024
#: The level a cached file is compressed with: computed once per file and process, so the smallest output wins.
STATIC_COMPRESS_LEVEL = 9

_CacheKey = tuple[str, int, int]
_compressed_cache: OrderedDict[_CacheKey, bytes] = OrderedDict()
_compressed_cache_bytes = 0


def is_hashed_asset(full_path: str | os.PathLike[str]) -> bool:
    """True for a build chunk under ``chat/assets/`` whose name carries its content hash."""
    path = Path(full_path)
    if tuple(part.lower() for part in path.parent.parts[-2:]) != HASHED_ASSET_DIR:
        return False
    return bool(_HASHED_NAME.search(path.name))


def clear_compressed_cache() -> None:
    global _compressed_cache_bytes
    _compressed_cache.clear()
    _compressed_cache_bytes = 0


def _remember(key: _CacheKey, value: bytes) -> None:
    global _compressed_cache_bytes
    if len(value) > CACHE_BUDGET_BYTES:
        return
    previous = _compressed_cache.pop(key, None)
    if previous is not None:
        _compressed_cache_bytes -= len(previous)
    _compressed_cache[key] = value
    _compressed_cache_bytes += len(value)
    while _compressed_cache_bytes > CACHE_BUDGET_BYTES and _compressed_cache:
        _old_key, old_value = _compressed_cache.popitem(last=False)
        _compressed_cache_bytes -= len(old_value)


def _read_and_compress(path: str) -> bytes:
    with open(path, "rb") as handle:
        return gzip_bytes(handle.read(), level=STATIC_COMPRESS_LEVEL)


async def compressed_file_bytes(path: str, stat_result: os.stat_result) -> bytes:
    """The file's gzip bytes, compressed in a worker thread on first use and then served from memory."""
    key = (path, int(stat_result.st_size), int(stat_result.st_mtime_ns))
    cached = _compressed_cache.get(key)
    if cached is not None:
        _compressed_cache.move_to_end(key)
        return cached
    compressed = await anyio.to_thread.run_sync(_read_and_compress, path)
    _remember(key, compressed)
    return compressed


class SpaStaticFiles(StaticFiles):
    """``StaticFiles`` with long-lived caching for hashed chunks and in-memory gzip for text files."""

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        request_headers = Headers(scope=scope)
        response = FileResponse(full_path, status_code=status_code, stat_result=stat_result)
        if is_hashed_asset(full_path):
            response.headers["Cache-Control"] = IMMUTABLE_CACHE_CONTROL
        if _compressible_file(response, stat_result):
            response.headers.add_vary_header("Accept-Encoding")
        if self.is_not_modified(response.headers, request_headers):
            return NotModifiedResponse(response.headers)
        return response

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if not isinstance(response, FileResponse) or response.status_code != 200 or response.stat_result is None:
            return response
        request_headers = Headers(scope=scope)
        if scope.get("method") != "GET" or "range" in request_headers or not accepts_gzip(request_headers):
            return response
        if not _compressible_file(response, response.stat_result):
            return response
        body = await compressed_file_bytes(str(response.path), response.stat_result)
        if len(body) >= response.stat_result.st_size:
            return response
        headers = {
            name: value
            for name, value in response.headers.items()
            if name not in ("content-length", "accept-ranges")
        }
        headers["content-encoding"] = "gzip"
        if "etag" in headers:
            headers["etag"] = weak_etag(headers["etag"])
        return Response(content=body, status_code=200, headers=headers)


def _compressible_file(response: FileResponse, stat_result: os.stat_result) -> bool:
    return (
        MINIMUM_SIZE <= stat_result.st_size <= MAX_COMPRESSED_SOURCE_BYTES
        and is_compressible_media_type(response.media_type)
    )


__all__ = [
    "IMMUTABLE_CACHE_CONTROL",
    "SpaStaticFiles",
    "clear_compressed_cache",
    "compressed_file_bytes",
    "is_hashed_asset",
]
