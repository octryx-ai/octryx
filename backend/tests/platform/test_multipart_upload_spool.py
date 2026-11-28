from __future__ import annotations

import inspect
from tempfile import SpooledTemporaryFile

import pytest
from fastapi.routing import APIRoute
from starlette import formparsers

from app.http_multipart_route import BoundedFormRoute, SelfAuthenticatedFormRoute, _body_kind
from app.main import app
from app.multipart_admission_policy import KNOWLEDGE_EVIDENCE_REQUEST_BYTES, MAX_FORM_FILES
from app.services.auth.tokens import create_access_token
from tests.support.multipart_admission_support import BOUNDARY, MULTIPART_CONTENT_TYPE, WORKSPACE_PATH

# Over Starlette's in-memory spool, under the Knowledge route's limit: a parse would write it to disk.
SPOOLED_PART = b"x" * (2 * 1024 * 1024)

#: Form routes that authenticate by what the form carries (a password, an OAuth grant, RFC 6749 and RFC 7009): they
#: take urlencoded only.
FORM_SELF_AUTHENTICATED = {
    "/chat/login": "the password is in the form",
    "/admin/login": "the password is in the form",
    "/api/v1/auth/login": "the password is in the form",
    "/chat/setup": "first-run setup, before any account exists",
    "/admin/setup": "first-run setup, before any account exists",
    "/oauth/token": "the grant is in the form (RFC 6749)",
    "/oauth/revoke": "the token to revoke is in the form (RFC 7009)",
}


def _body(payload: bytes) -> bytes:
    return (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"runbook.txt\"\r\n"
            f"Content-Type: text/plain\r\n\r\n").encode() + payload + f"\r\n--{BOUNDARY}--\r\n".encode()


@pytest.fixture
def spooled(monkeypatch) -> list[object]:
    created: list[object] = []

    class Recorded(SpooledTemporaryFile):
        def __init__(self, *args, **kwargs):
            created.append(self)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", Recorded)
    return created


async def _upload(client, path: str, headers: dict) -> int:
    response = await client.post(path, content=_body(SPOOLED_PART),
                                 headers={**headers, "content-type": MULTIPART_CONTENT_TYPE})
    return response.status_code


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [
    {},
    {"authorization": "Bearer not-a-token"},
    {"cookie": "access_token=not-a-token"},
    {"x-api-key": "not-a-key"},
], ids=["none", "bogus-bearer", "bogus-cookie", "bogus-api-key"])
async def test_an_upload_without_a_valid_credential_is_refused_before_any_temp_file(client, spooled, headers):
    assert await _upload(client, WORKSPACE_PATH, headers) == 401 and spooled == []


@pytest.mark.asyncio
async def test_a_streamed_anonymous_upload_is_refused_before_any_temp_file_is_written(client, spooled):
    async def chunks():
        yield _body(SPOOLED_PART)

    response = await client.post(WORKSPACE_PATH, content=chunks(), headers={"content-type": MULTIPART_CONTENT_TYPE})
    assert response.status_code == 401 and spooled == []


@pytest.mark.asyncio
async def test_a_signed_in_upload_of_that_size_is_spooled(client, auth_headers, spooled):
    await _upload(client, WORKSPACE_PATH, auth_headers)
    assert spooled, "the spy sees a spool, so its absence above means none was written"


@pytest.mark.asyncio
async def test_a_browser_upload_is_signed_in_by_its_cookie_next_to_cookies_the_strict_parser_rejects(
    client, auth_headers, spooled,
):
    token = auth_headers["Authorization"].removeprefix("Bearer ")
    cookie = f'lang=en US; consent={{"a":1}}; access_token={token}'
    await _upload(client, WORKSPACE_PATH, {"cookie": cookie})
    assert spooled, "the session cookie authenticated the upload"


@pytest.mark.asyncio
async def test_a_live_session_cookie_admits_the_upload_next_to_a_stale_bearer(client, auth_headers, spooled):
    token = auth_headers["Authorization"].removeprefix("Bearer ")
    await _upload(client, WORKSPACE_PATH, {"authorization": "Bearer stale-token", "cookie": f"access_token={token}"})
    assert spooled, "any valid credential admits, as the route's own login does"


@pytest.mark.asyncio
@pytest.mark.parametrize("signed_in", [False, True])
async def test_an_oversized_upload_is_refused_before_any_temp_file_is_written(client, auth_headers, spooled, signed_in):
    response = await client.post(WORKSPACE_PATH, content=b"x", headers={
        **(auth_headers if signed_in else {}), "content-type": MULTIPART_CONTENT_TYPE,
        "content-length": str(KNOWLEDGE_EVIDENCE_REQUEST_BYTES + 1)})
    assert response.status_code == 413 and spooled == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", sorted(FORM_SELF_AUTHENTICATED))
async def test_a_self_authenticated_form_route_refuses_multipart_before_any_temp_file(client, spooled, path):
    assert await _upload(client, path, {}) == 415 and spooled == []


@pytest.mark.asyncio
async def test_a_json_route_refuses_form_content_before_any_temp_file(client, auth_headers, spooled):
    assert await _upload(client, "/chat/api/send", auth_headers) == 415 and spooled == []


@pytest.mark.asyncio
async def test_a_form_with_more_files_than_the_limit_is_refused(client, auth_headers):
    files = [("files", (f"note-{index}.txt", b"synthetic", "text/plain")) for index in range(MAX_FORM_FILES + 1)]
    response = await client.post("/chat/api/upload", files=files, headers=auth_headers)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_a_bounded_route_answers_a_credential_less_urlencoded_form_itself(client):
    # Only a multipart body is checked before the route (an urlencoded one never spools): the route's own form
    # validation answers, so the form reached it.
    response = await client.post("/oauth/authorize/decision", data={"approve": "true"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_a_valid_bearer_token_passes_before_the_route_checks_its_user(client, spooled):
    token = create_access_token("synthetic-user-without-a-row")
    assert await _upload(client, WORKSPACE_PATH, {"authorization": f"Bearer {token}"}) == 401
    assert spooled, "the signature was enough to parse; the route's own login check refused the unknown user"


def _form_routes() -> dict[str, APIRoute]:
    found: dict[str, APIRoute] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if _body_kind(route) == "form" or ".form(" in inspect.getsource(route.endpoint):
            found[f"{sorted(route.methods)} {route.path}"] = route
    return found


def test_every_form_route_is_bounded_or_a_named_self_authenticated_one():
    routes = _form_routes()
    assert routes, "the inventory found the form routes"
    unexplained = [key for key, route in routes.items() if not (
        isinstance(route, BoundedFormRoute)
        or (isinstance(route, SelfAuthenticatedFormRoute) and route.path in FORM_SELF_AUTHENTICATED))]
    assert unexplained == []
    named = {route.path for route in routes.values() if isinstance(route, SelfAuthenticatedFormRoute)}
    assert named == set(FORM_SELF_AUTHENTICATED), "every named exception is still a form route, and nothing else is"


def test_every_upload_route_is_bounded():
    uploads = [route for route in _form_routes().values()
               if any("UploadFile" in str(param.annotation)
                      for param in inspect.signature(route.endpoint).parameters.values())]
    assert uploads and all(isinstance(route, BoundedFormRoute) for route in uploads)
