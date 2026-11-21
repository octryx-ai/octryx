"""Complete dynamic responses are gzip-compressed above the threshold, while streams, ranges, binaries and already encoded bodies pass through unchanged."""

from __future__ import annotations

import gzip
import json

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.datastructures import Headers

from app.middleware.transport.compression import (
    ResponseCompressionMiddleware,
    accepts_gzip,
    is_compressible_media_type,
)
from tests.conftest import ADMIN_PASSWORD
from tests.response_compression_support import GZIP, IDENTITY, _fresh_cache, _raw_client, _wire  # noqa: F401

# --- dynamic responses ------------------------------------------------------------------------------------------

BIG_JSON = {"items": [{"id": index, "title": f"Work item {index}"} for index in range(200)]}


def _dynamic_app() -> FastAPI:
    app = FastAPI()

    @app.get("/json")
    async def big_json():
        return BIG_JSON

    @app.get("/small")
    async def small_json():
        return {"ok": True}

    @app.get("/sse")
    async def sse():
        async def events():
            for index in range(3):
                yield f"data: {'x' * 600} {index}\n\n"
        return StreamingResponse(events(), media_type="text/event-stream")

    @app.get("/sse-single")
    async def sse_single():
        return Response(content="data: " + "x" * 4000 + "\n\n", media_type="text/event-stream")

    @app.get("/ndjson")
    async def ndjson():
        async def lines():
            for index in range(3):
                yield json.dumps({"index": index, "pad": "y" * 800}) + "\n"
        return StreamingResponse(lines(), media_type="application/x-ndjson")

    @app.get("/png")
    async def png():
        return Response(content=b"\x89PNG" + b"\x00" * 5000, media_type="image/png")

    @app.get("/encoded")
    async def encoded():
        return Response(content=gzip.compress(b"z" * 5000), media_type="text/plain",
                        headers={"content-encoding": "gzip"})

    @app.get("/partial")
    async def partial():
        return PlainTextResponse("p" * 5000, status_code=206, headers={"content-range": "bytes 0-4999/9000"})

    @app.get("/no-transform")
    async def no_transform():
        return PlainTextResponse("n" * 5000, headers={"cache-control": "no-transform"})

    @app.get("/tagged")
    async def tagged():
        return JSONResponse(BIG_JSON, headers={"etag": '"v1"'})

    app.add_middleware(ResponseCompressionMiddleware)
    return app


@pytest_asyncio.fixture
async def dynamic_client():
    async with _raw_client(_dynamic_app()) as client:
        yield client


async def test_a_complete_json_body_is_compressed(dynamic_client):
    status, headers, body = await _wire(dynamic_client, "GET", "/json", GZIP)

    assert status == 200
    assert headers["content-encoding"] == "gzip"
    assert json.loads(gzip.decompress(body)) == BIG_JSON
    assert int(headers["content-length"]) == len(body)
    assert "accept-encoding" in headers["vary"].lower()


async def test_without_gzip_or_below_the_threshold_the_body_is_unchanged(dynamic_client):
    _status, headers, body = await _wire(dynamic_client, "GET", "/json", IDENTITY)
    assert "content-encoding" not in headers and json.loads(body) == BIG_JSON

    _status, headers, body = await _wire(dynamic_client, "GET", "/json", {"accept-encoding": "gzip;q=0, br"})
    assert "content-encoding" not in headers and json.loads(body) == BIG_JSON

    _status, headers, body = await _wire(dynamic_client, "GET", "/small", GZIP)
    assert "content-encoding" not in headers and json.loads(body) == {"ok": True}


@pytest.mark.parametrize("path", ["/sse", "/sse-single", "/ndjson", "/png", "/partial", "/no-transform"])
async def test_streams_ranges_and_binaries_are_passed_through(dynamic_client, path):
    status, headers, body = await _wire(dynamic_client, "GET", path, GZIP)

    assert status in (200, 206)
    assert "content-encoding" not in headers
    assert len(body) > 1024


@pytest.mark.parametrize("media_type", ["text/plain", "application/x-ndjson", "text/event-stream"])
async def test_each_chunk_of_a_stream_is_forwarded_as_it_comes(media_type):
    """Measured at the ASGI boundary (a test client buffers): every chunk is sent on, unchanged and unheld."""
    chunks = [f"chunk {index} ".encode() + b"q" * 2000 for index in range(3)]
    forwarded: list[dict] = []

    async def stream_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", media_type.encode())]})
        for index, chunk in enumerate(chunks):
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
            # The previous chunk already reached the server before the next one is produced.
            assert forwarded[-1]["body"] == chunk, index
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def receive():  # pragma: no cover - never called
        return {"type": "http.disconnect"}

    async def send(message):
        forwarded.append(message)

    scope = {"type": "http", "method": "GET", "path": "/", "headers": [(b"accept-encoding", b"gzip")]}
    await ResponseCompressionMiddleware(stream_app)(scope, receive, send)

    start = forwarded[0]
    assert start["type"] == "http.response.start"
    assert b"content-encoding" not in dict(start["headers"])
    assert [message["body"] for message in forwarded[1:]] == [*chunks, b""]


async def test_an_encoded_body_is_not_compressed_twice(dynamic_client):
    _status, headers, body = await _wire(dynamic_client, "GET", "/encoded", GZIP)
    assert headers["content-encoding"] == "gzip"
    assert gzip.decompress(body) == b"z" * 5000


async def test_the_etag_of_a_compressed_body_becomes_weak(dynamic_client):
    _status, headers, _body = await _wire(dynamic_client, "GET", "/tagged", GZIP)
    assert headers["content-encoding"] == "gzip"
    assert headers["etag"] == 'W/"v1"'


def test_accept_encoding_parsing():
    assert accepts_gzip(Headers({"accept-encoding": "gzip"}))
    assert accepts_gzip(Headers({"accept-encoding": "br;q=1.0, gzip;q=0.8"}))
    assert accepts_gzip(Headers({"accept-encoding": "*"}))
    assert not accepts_gzip(Headers({"accept-encoding": "gzip;q=0"}))
    assert not accepts_gzip(Headers({"accept-encoding": "*, gzip;q=0"}))
    assert not accepts_gzip(Headers({"accept-encoding": "identity"}))
    assert not accepts_gzip(Headers({}))


def test_compressible_media_types():
    for media_type in ("text/javascript; charset=utf-8", "text/css", "application/json", "image/svg+xml",
                       "application/problem+json", "text/html", "application/wasm"):
        assert is_compressible_media_type(media_type), media_type
    for media_type in ("text/event-stream", "image/png", "font/woff2", "application/gzip", "application/zip",
                       "application/octet-stream", "", None):
        assert not is_compressible_media_type(media_type), media_type


# --- the whole application ----------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_api_answer_through_the_full_middleware_stack_is_compressed(client):
    login = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 303
    response = await client.get("/chat/api/bootstrap", headers={"accept-encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers.get("content-encoding") == "gzip"
    assert "currentUser" in response.json()  # httpx decodes it transparently
