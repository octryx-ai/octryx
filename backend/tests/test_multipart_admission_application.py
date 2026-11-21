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
from tests.multipart_admission_support import (
    CHUNK,
    LIMIT,
    MULTIPART_CONTENT_TYPE,
    OVERSIZE_CHUNKS,
    WORKSPACE_PATH,
    _part_header,
)

# --- The real application ---------------------------------------------------


@pytest.fixture
def parser_spy(monkeypatch):
    """Fail the test if Starlette's multipart parser is entered at all."""
    calls: list[int] = []

    async def _tripwire(self, *args, **kwargs):
        calls.append(1)
        raise AssertionError("the multipart parser must not run for a rejected request")

    monkeypatch.setattr(MultiPartParser, "parse", _tripwire)
    return calls


@pytest.fixture
def low_ceiling(monkeypatch):
    """Lower the process ceiling the real middleware reads, for one test."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_multipart_request_bytes", LIMIT)
    return LIMIT


@pytest.fixture
def created_spool_files(monkeypatch):
    """Every ``SpooledTemporaryFile`` Starlette's multipart parser creates."""
    created: list[object] = []
    real = formparsers.SpooledTemporaryFile

    def _recording(*args, **kwargs):
        spool = real(*args, **kwargs)
        created.append(spool)
        return spool

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", _recording)
    return created


# --- Middleware order -------------------------------------------------------


def _middleware_chain() -> list[str]:
    """The application's middleware, outermost first."""
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
async def test_an_unauthenticated_streamed_upload_without_content_length_is_refused(client, low_ceiling):
    """No declared length: the parser is the consumer, so it starts and is cut off.

    The parser cannot be kept out of a streamed request — it is what pulls the
    bytes — so the guarantee here is the outcome and the budget: the answer is the
    boundary's 413 rather than the parser's 400 or the route's 401, and the bytes
    the parser was handed stayed within the limit (pinned at the ASGI layer by
    ``test_a_streamed_body_without_content_length_is_bounded_by_raw_bytes``).
    """

    async def _chunks():
        yield _part_header()
        for _ in range(OVERSIZE_CHUNKS):
            yield b"x" * CHUNK

    response = await client.post(
        WORKSPACE_PATH,
        content=_chunks(),
        headers={"content-type": MULTIPART_CONTENT_TYPE},
    )

    assert response.status_code == TOO_LARGE_STATUS
    assert response.json()["detail"] == TOO_LARGE_DETAIL


@pytest.mark.asyncio
async def test_a_streaming_overrun_closes_the_spool_file_the_parser_created(
    client, low_ceiling, created_spool_files
):
    """The abort must land in the parser's own cleanup path.

    ``MultiPartParser.parse`` closes the ``SpooledTemporaryFile`` of every part it
    had already begun only inside ``except (MultiPartException, OSError)``. An
    abort signal outside that tuple leaves the spool of an aborted upload open,
    which is the resource this boundary exists to protect — so the regression is
    about the file objects, not only about the status code.
    """

    async def _chunks():
        yield _part_header()
        for _ in range(OVERSIZE_CHUNKS):
            yield b"x" * CHUNK

    response = await client.post(
        WORKSPACE_PATH,
        content=_chunks(),
        headers={"content-type": MULTIPART_CONTENT_TYPE},
    )

    assert response.status_code == TOO_LARGE_STATUS
    # Not vacuous: the parser really did start a file part before the cut.
    assert created_spool_files
    assert [spool.closed for spool in created_spool_files] == [True] * len(created_spool_files)


@pytest.mark.asyncio
async def test_a_within_limit_upload_still_reaches_authentication(client, low_ceiling):
    """Pass-through is unchanged: the request is parsed and answered by the route."""
    response = await client.post(
        WORKSPACE_PATH,
        files={"file": ("runbook.txt", b"x" * 64, "text/plain")},
        data={"source_key": "runbook", "display_title": "Runbook"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_the_boundary_sits_inside_the_trusted_proxy_boundary(client, low_ceiling):
    """Client identity stays outermost: a rejected request still resolved its client identity."""
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
    """Starlette adds middleware inside-out, so this order is easy to get wrong.

    The boundary must be *inside* CORS and the request-context/audit/rate-limit
    layers — so a rejection is labelled, counted and auditable — while the
    trusted-proxy boundary stays outermost and nothing above the boundary
    reads the request body. The panel CSRF boundary sits directly above
    it: it only inspects headers, so the parser boundary stays intact, and a
    cross-site upload is refused before a byte of it is parsed.
    """
    chain = _middleware_chain()

    assert chain == [
        "TrustedProxyBoundaryMiddleware",
        "rate_limit_middleware",
        "audit_middleware",
        "rls_middleware",
        "observability_middleware",
        "request_context_middleware",
        "_validate_origin",
        # Names every request over OCTRYX_SLOW_REQUEST_SECONDS; times all inner layers, reads no body.
        "SlowRequestLogMiddleware",
        "ResponseCompressionMiddleware",
        "CORSMiddleware",
        "PanelCsrfBoundaryMiddleware",
        "MultipartAdmissionMiddleware",
    ]


@pytest.mark.asyncio
async def test_a_rejected_upload_from_an_allowed_origin_carries_its_cors_header(client, low_ceiling):
    """A browser must be able to read the rejection instead of a CORS error."""
    origin = "http://localhost:5173"

    response = await client.post(
        WORKSPACE_PATH,
        files={"file": ("runbook.txt", b"x" * (LIMIT * 2), "text/plain")},
        headers={"origin": origin},
    )

    assert response.status_code == TOO_LARGE_STATUS
    assert response.headers["access-control-allow-origin"] == origin
