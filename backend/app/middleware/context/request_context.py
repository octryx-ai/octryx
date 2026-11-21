from __future__ import annotations

from fastapi import Request

from ...services.request_context import (
    generate_request_id,
    reset_current_request_id,
    safe_request_id,
    set_current_request_id,
)


async def request_context_middleware(request: Request, call_next):
    # A caller-supplied X-Request-ID must be a safe, length-bounded
    # token, never arbitrary input; ``safe_request_id`` owns that rule.
    request_id = safe_request_id(request.headers.get("x-request-id")) or generate_request_id()
    request.state.request_id = request_id
    token = set_current_request_id(request_id)
    try:
        response = await call_next(request)
    finally:
        reset_current_request_id(token)
    response.headers["X-Request-ID"] = request_id
    return response
