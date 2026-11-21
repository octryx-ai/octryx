"""Static bundles are cached for a year and served gzip-compressed; streams, ranges and binaries are untouched.

Without this, megabytes of JavaScript go out per cold load uncompressed and without ``Cache-Control``. Hashed chunks
under ``chat/assets/`` are immutable, the page shell stays ``no-store``, complete text responses of 1 KiB and more
are gzip-compressed, and a stream (SSE, NDJSON, file chunks) is never buffered by the compression.
"""

from __future__ import annotations

import gzip

import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.middleware.transport.compression import ResponseCompressionMiddleware
from app.web.static_files import IMMUTABLE_CACHE_CONTROL, SpaStaticFiles, is_hashed_asset
from tests.response_compression_support import GZIP, IDENTITY, _fresh_cache, _raw_client, _wire  # noqa: F401

VENDOR = "/admin/static/chat/assets/vendor-D9lvy8W_.js"


VENDOR_BODY = ("export const vendor = 'x';\n" * 400).encode()


LOGO = "/chat/static/chat/octryx-logo.svg"


LOGO_BODY = ('<svg xmlns="http://www.w3.org/2000/svg">' + "<rect/>" * 400 + "</svg>").encode()


TINY_CHUNK = "/admin/static/chat/assets/tiny-AbCd1234.js"


IMAGE = "/admin/static/chat/assets/hero-Xy_9-8Zq.png"


@pytest.fixture
def static_dir(tmp_path):
    assets = tmp_path / "chat" / "assets"
    assets.mkdir(parents=True)
    (assets / "vendor-D9lvy8W_.js").write_bytes(VENDOR_BODY)
    (assets / "tiny-AbCd1234.js").write_bytes(b"export {};\n")
    (assets / "hero-Xy_9-8Zq.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 20)
    (tmp_path / "chat" / "octryx-logo.svg").write_bytes(LOGO_BODY)
    return tmp_path


@pytest_asyncio.fixture
async def static_client(static_dir):
    app = FastAPI()
    app.mount("/chat/static", SpaStaticFiles(directory=str(static_dir)), name="chat-static")
    app.mount("/admin/static", SpaStaticFiles(directory=str(static_dir)), name="admin-static")
    async with _raw_client(app) as client:
        yield client


# --- the SPA's static mounts ----------------------------------------------------------------------------------


def test_only_build_chunks_with_a_content_hash_are_immutable():
    assert is_hashed_asset("/srv/static/chat/assets/vendor-D9lvy8W_.js")
    assert is_hashed_asset("/srv/static/chat/assets/serviceNowAuthModel-Omf-8vk5.js")
    assert is_hashed_asset("/srv/static/chat/assets/main-C7BZYFcI.css")
    assert not is_hashed_asset("/srv/static/chat/assets/AdminRuntimesTab-test.js")
    assert not is_hashed_asset("/srv/static/chat/favicon.svg")
    assert not is_hashed_asset("/srv/static/chat/index.html")
    assert not is_hashed_asset("/srv/static/chat/guards/tools-config-guard-AbCd1234.js")


async def test_a_hashed_chunk_is_gzip_compressed_and_cached_for_a_year(static_client):
    status, headers, body = await _wire(static_client, "GET", VENDOR, GZIP)

    assert status == 200
    assert headers["content-encoding"] == "gzip"
    assert gzip.decompress(body) == VENDOR_BODY
    assert int(headers["content-length"]) == len(body) < len(VENDOR_BODY) / 10
    assert headers["cache-control"] == IMMUTABLE_CACHE_CONTROL
    assert "accept-encoding" in headers["vary"].lower()
    assert "javascript" in headers["content-type"]
    assert headers["etag"].startswith('W/"')
    assert "accept-ranges" not in headers

    # Served again from memory: the same bytes.
    assert (await _wire(static_client, "GET", VENDOR, GZIP))[2] == body


async def test_a_client_without_gzip_gets_the_file_itself(static_client):
    status, headers, body = await _wire(static_client, "GET", VENDOR, IDENTITY)

    assert status == 200
    assert "content-encoding" not in headers
    assert body == VENDOR_BODY
    assert headers["cache-control"] == IMMUTABLE_CACHE_CONTROL
    assert headers["accept-ranges"] == "bytes"


async def test_a_range_request_answers_the_exact_bytes_uncompressed(static_client):
    status, headers, body = await _wire(static_client, "GET", VENDOR, {**GZIP, "range": "bytes=0-9"})

    assert status == 206
    assert "content-encoding" not in headers
    assert body == VENDOR_BODY[:10]
    assert headers["content-range"] == f"bytes 0-9/{len(VENDOR_BODY)}"


async def test_head_and_revalidation_keep_working(static_client):
    status, headers, body = await _wire(static_client, "HEAD", VENDOR, GZIP)
    assert (status, body) == (200, b"")
    assert "content-encoding" not in headers

    _status, compressed_headers, _body = await _wire(static_client, "GET", VENDOR, GZIP)
    weak = compressed_headers["etag"]
    status, headers, body = await _wire(static_client, "GET", VENDOR, {**GZIP, "if-none-match": weak})
    assert (status, body) == (304, b"")
    assert headers["cache-control"] == IMMUTABLE_CACHE_CONTROL


async def test_a_fixed_name_file_is_compressed_but_not_made_immutable(static_client):
    status, headers, body = await _wire(static_client, "GET", LOGO, GZIP)

    assert status == 200
    assert headers["content-encoding"] == "gzip"
    assert gzip.decompress(body) == LOGO_BODY
    assert "cache-control" not in headers  # revalidated by ETag / Last-Modified
    assert "last-modified" in headers


async def test_tiny_and_binary_files_are_served_as_they_are(static_client):
    _status, tiny_headers, tiny = await _wire(static_client, "GET", TINY_CHUNK, GZIP)
    assert "content-encoding" not in tiny_headers and tiny == b"export {};\n"
    assert tiny_headers["cache-control"] == IMMUTABLE_CACHE_CONTROL

    _status, image_headers, image = await _wire(static_client, "GET", IMAGE, GZIP)
    assert "content-encoding" not in image_headers and image.startswith(b"\x89PNG")
    assert image_headers["cache-control"] == IMMUTABLE_CACHE_CONTROL


def test_the_application_mounts_the_spa_with_caching_and_compression():
    from starlette.routing import Mount

    from app.main import app

    mounts = {route.path: route.app for route in app.routes if isinstance(route, Mount)}
    assert isinstance(mounts["/chat/static"], SpaStaticFiles)
    assert isinstance(mounts["/admin/static"], SpaStaticFiles)
    assert any(entry.cls is ResponseCompressionMiddleware for entry in app.user_middleware)
