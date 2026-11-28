"""The real application: unauthenticated oversized uploads reach neither the multipart parser nor the route, and the boundary's place in the middleware chain."""

from __future__ import annotations

import pytest
from starlette import formparsers
from starlette.formparsers import MultiPartParser

from app.middleware.security.multipart_admission import (
    TOO_LARGE_DETAIL,
    TOO_LARGE_STATUS,
    MultipartAdmissionMiddleware,
)
from tests.support.multipart_admission_support import (
    CHUNK,
    LIMIT,
    MULTIPART_CONTENT_TYPE,
    OVERRIDDEN_USER_CREDENTIAL,
    OVERSIZE_CHUNKS,
    WORKSPACE_PATH,
    _part_header,
)


@pytest.fixture
def parser_spy(monkeypatch):
    calls: list[int] = []

    async def _tripwire(self, *args, **kwargs):
        calls.append(1)
        raise AssertionError("the multipart parser must not run for a rejected request")

    monkeypatch.setattr(MultiPartParser, "parse", _tripwire)
    return calls


@pytest.fixture
def low_ceiling(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_multipart_request_bytes", LIMIT)
    return LIMIT


@pytest.fixture
def created_spool_files(monkeypatch):
    created: list[object] = []
    real = formparsers.SpooledTemporaryFile

    def _recording(*args, **kwargs):
        spool = real(*args, **kwargs)
        created.append(spool)
        return spool

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", _recording)
    return created


def _middleware_chain() -> list[str]:
    from app.main import app

    names: list[str] = []
    for entry in app.user_middleware:
        dispatch = (entry.kwargs or {}).get("dispatch")
        names.append(getattr(dispatch, "__name__", None) or entry.cls.__name__)
    return names


@pytest.mark.asyncio
async def test_an_unauthenticated_oversized_upload_reaches_neither_parser_nor_route(
    client, low_ceiling, parser_spy
):
    response = await client.post(
        WORKSPACE_PATH,
        files={"file": ("runbook.txt", b"x" * (LIMIT * 2), "text/plain")},
        data={"source_key": "runbook", "display_title": "Runbook"},
    )

    assert response.status_code == TOO_LARGE_STATUS
    assert response.json()["detail"] == TOO_LARGE_DETAIL
    assert parser_spy == []


@pytest.mark.asyncio
async def test_a_streamed_upload_without_content_length_is_refused(client, low_ceiling):
    async def _chunks():
        yield _part_header()
        for _ in range(OVERSIZE_CHUNKS):
            yield b"x" * CHUNK

    response = await client.post(
        WORKSPACE_PATH,
        content=_chunks(),
        headers={"content-type": MULTIPART_CONTENT_TYPE, **OVERRIDDEN_USER_CREDENTIAL},
    )

    assert response.status_code == TOO_LARGE_STATUS
    assert response.json()["detail"] == TOO_LARGE_DETAIL


@pytest.mark.asyncio
async def test_a_streaming_overrun_closes_the_spool_file_the_parser_created(
    client, low_ceiling, created_spool_files
):
    async def _chunks():
        yield _part_header()
        for _ in range(OVERSIZE_CHUNKS):
            yield b"x" * CHUNK

    response = await client.post(
        WORKSPACE_PATH,
        content=_chunks(),
        headers={"content-type": MULTIPART_CONTENT_TYPE, **OVERRIDDEN_USER_CREDENTIAL},
    )

    assert response.status_code == TOO_LARGE_STATUS
    # Not vacuous: the parser really did start a file part before the cut.
    assert created_spool_files
    assert [spool.closed for spool in created_spool_files] == [True] * len(created_spool_files)


@pytest.mark.asyncio
async def test_a_within_limit_upload_still_reaches_authentication(client, low_ceiling):
    response = await client.post(
        WORKSPACE_PATH,
        files={"file": ("runbook.txt", b"x" * 64, "text/plain")},
        data={"source_key": "runbook", "display_title": "Runbook"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_the_boundary_sits_inside_the_trusted_proxy_boundary(client, low_ceiling):
    from app.trusted_proxy_policy import SCOPE_STATE_KEY

    seen: dict[str, object] = {}
    original = MultipartAdmissionMiddleware.__call__

    async def _observing(self, scope, receive, send):
        seen["identity"] = scope.get(SCOPE_STATE_KEY)
        return await original(self, scope, receive, send)

    MultipartAdmissionMiddleware.__call__ = _observing
    try:
        response = await client.post(
            WORKSPACE_PATH,
            files={"file": ("runbook.txt", b"x" * (LIMIT * 2), "text/plain")},
        )
    finally:
        MultipartAdmissionMiddleware.__call__ = original

    assert response.status_code == TOO_LARGE_STATUS
    assert seen["identity"] is not None


def test_the_admission_boundary_sits_between_cors_and_the_router():
    chain = _middleware_chain()

    assert chain == [
        "TrustedProxyBoundaryMiddleware",
        "rate_limit_middleware",
        "audit_middleware",
        "observability_middleware",
        "request_context_middleware",
        "_validate_origin",
        "DataViewerScopeMiddleware",
        # Names every request over OCTRYX_SLOW_REQUEST_SECONDS; times all inner layers, reads no body.
        "SlowRequestLogMiddleware",
        "ResponseCompressionMiddleware",
        "CORSMiddleware",
        "PanelCsrfBoundaryMiddleware",
        "MultipartAdmissionMiddleware",
    ]


@pytest.mark.asyncio
async def test_a_rejected_upload_from_an_allowed_origin_carries_its_cors_header(client, low_ceiling):
    origin = "http://localhost:5173"

    response = await client.post(
        WORKSPACE_PATH,
        files={"file": ("runbook.txt", b"x" * (LIMIT * 2), "text/plain")},
        headers={"origin": origin},
    )

    assert response.status_code == TOO_LARGE_STATUS
    assert response.headers["access-control-allow-origin"] == origin
