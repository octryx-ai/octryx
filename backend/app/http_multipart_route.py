"""Form parsing at the route, before FastAPI reads the body: multipart only for a verified credential or not at all,
urlencoded with the platform's limits, and no form content on a JSON route."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, params
from fastapi.routing import APIRoute
from starlette.requests import Request
from starlette.responses import Response

from .db import get_db
from .http_security import API_KEY_HEADER
from .multipart_admission_policy import (
    MAX_FORM_FIELD_BYTES,
    MAX_FORM_FIELDS,
    MAX_FORM_FILES,
    is_multipart_content_type,
)
from .services.api_key import authenticate_api_key
from .services.auth.tokens import cookie_access_token, decode_token

FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"


# Admitted when any credential the request presents verifies: a route's own login accepts whichever one is valid (a
# stale bearer next to a live session cookie is still a signed-in browser). A token by its signature, a key by lookup.
async def verified_credential(request: Request) -> bool:
    scheme, _, bearer = str(request.headers.get("authorization") or "").partition(" ")
    tokens = [bearer.strip() if scheme.lower() == "bearer" else "", cookie_access_token(request)]
    for token in filter(None, tokens):
        try:
            decode_token(token, allow_phone=True)
        except HTTPException:
            continue
        return True
    raw_key = str(request.headers.get(API_KEY_HEADER) or "").strip()
    if not raw_key:
        return False
    sessions = request.app.dependency_overrides.get(get_db, get_db)()
    db = await anext(sessions)
    try:
        await authenticate_api_key(db, raw_key)
    except HTTPException:
        return False
    finally:
        await sessions.aclose()
    return True


def _body_kind(route: APIRoute) -> str:
    field = getattr(route, "body_field", None)
    if field is None:
        return "none"
    return "form" if isinstance(getattr(field, "field_info", None), params.Form) else "json"


class _FormBoundaryRoute(APIRoute):
    login_required = True

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()
        body = _body_kind(self)

        async def bounded(request: Request) -> Response:
            content_type = str(request.headers.get("content-type") or "").lower()
            multipart = is_multipart_content_type(content_type)
            if body == "none" or not (multipart or content_type.startswith(FORM_CONTENT_TYPE)):
                return await handler(request)
            if body == "json":
                raise HTTPException(status_code=415, detail="This endpoint takes JSON, not form content.")
            if multipart and not self.login_required:
                raise HTTPException(status_code=415, detail="This form is sent urlencoded, not as multipart.")
            # Starlette spools a file part to a temp file while it parses, before the route's own login check runs.
            if multipart and not await verified_credential(request):
                raise HTTPException(status_code=401, detail="Not authenticated")
            # Cached on the request: FastAPI's own parse after this reads the bounded form.
            await request.form(max_files=MAX_FORM_FILES, max_fields=MAX_FORM_FIELDS,
                               max_part_size=MAX_FORM_FIELD_BYTES)
            return await handler(request)

        return bounded


class BoundedFormRoute(_FormBoundaryRoute):
    login_required = True


# The form routes that authenticate by what the form carries (a password, an OAuth grant): no credential comes
# with them, so they never parse a multipart body.
class SelfAuthenticatedFormRoute(_FormBoundaryRoute):
    login_required = False


__all__ = ["BoundedFormRoute", "SelfAuthenticatedFormRoute", "verified_credential"]
