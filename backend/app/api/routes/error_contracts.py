from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.exception_handlers import http_exception_handler as fastapi_http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.exceptions.api import AuthenticationError, AuthorizationError, ConflictError
from app.exceptions.api import ValidationError as DomainValidationError
from app.exceptions.base import NotFoundError, OctryxError

from ...services.error_facts import error_facts, error_text
from ...services.request_context import get_current_request_id


def build_error_payload(
    *,
    status_code: int,
    detail: Any,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message = error or (detail if isinstance(detail, str) else "Request failed")
    payload: dict[str, Any] = {
        "error": message,
        "detail": detail,
        "status_code": status_code,
        "request_id": get_current_request_id(),
    }
    if extra:
        payload.update(extra)
    return payload


def _wants_json_error(request: Request) -> bool:
    path = request.url.path
    if path.startswith("/api/") or path.startswith("/admin/chat/api/"):
        return True
    accept = request.headers.get("accept", "")
    return "application/json" in accept.lower()


async def http_exception_handler(request: Request, exc: HTTPException):
    if 300 <= exc.status_code < 400 or not _wants_json_error(request):
        return await fastapi_http_exception_handler(request, exc)
    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_payload(status_code=exc.status_code, detail=exc.detail),
        headers=exc.headers,
    )



async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content=build_error_payload(status_code=404, detail=str(exc)),
    )


async def domain_validation_handler(request: Request, exc: DomainValidationError) -> JSONResponse:
    extra = {"field": exc.field} if exc.field else None
    return JSONResponse(
        status_code=400,
        content=build_error_payload(status_code=400, detail=str(exc), extra=extra),
    )


async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content=build_error_payload(status_code=409, detail=str(exc)),
    )


async def authentication_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content=build_error_payload(status_code=401, detail=str(exc)),
    )


async def authorization_handler(request: Request, exc: AuthorizationError) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content=build_error_payload(status_code=403, detail=str(exc)),
    )


async def domain_error_handler(request: Request, exc: OctryxError) -> JSONResponse:
    # ProviderError and ToolExecutionError wrap provider and tool text, so the message never leaves; the response
    # carries the fixed code and the class name.
    return JSONResponse(
        status_code=500,
        content=build_error_payload(
            status_code=500,
            detail=f"Request failed. {error_text('domain_error', exc)}",
            error="Request failed",
            extra=error_facts("domain_error", exc),
        ),
    )


def _json_safe(value):
    # A ValueError raised in a Pydantic validator lands as the exception object in ctx.error; JSONResponse cannot
    # serialise it, so the 422 would become a 500.
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=build_error_payload(
            status_code=422,
            detail="Validation failed",
            error="Validation failed",
            extra={"validation_errors": _json_safe(exc.errors())},
        ),
    )
