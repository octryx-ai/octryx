import logging

from fastapi import Request

from ...db import async_session_factory
from ...services.agent_gateway.contract import GATEWAY_ROUTE_PREFIXES, SEAT_MODEL_ROUTE_PREFIXES
from ...services.auth import resolve_bearer_principal_user_id
from ...services.request_context import (
    get_current_request_id,
    reset_current_rls_user_id,
    set_current_rls_user_id,
)

logger = logging.getLogger(__name__)
root_logger = logging.getLogger()


def _log_exception(message: str, *args: object) -> None:
    logger.exception(message, *args)
    if logger.disabled or not logger.propagate:
        root_logger.exception(message, *args)


async def rls_middleware(request: Request, call_next):
    """Expose the authenticated user to the DB layer for per-session RLS setup."""
    auth_header = request.headers.get("authorization")
    request_id = getattr(request.state, "request_id", None) or get_current_request_id()
    token = None

    # The seat route's bearer is a subscription token, not ours: never decoded, never logged.
    if auth_header and auth_header.startswith("Bearer ") and not request.url.path.startswith(SEAT_MODEL_ROUTE_PREFIXES):
        token = auth_header.split(" ", 1)[1]

    user_token = None
    if token:
        try:
            app = request.scope.get("app")
            session_factory = getattr(getattr(app, "state", None), "async_session_factory", async_session_factory)
            async with session_factory() as db:
                user_id = await resolve_bearer_principal_user_id(db, token)
                await db.commit()
        except Exception:
            if request.url.path.startswith(GATEWAY_ROUTE_PREFIXES):
                # A gateway login token is not a platform token: expected, so debug and no traceback. The
                # gateway routes authenticate it themselves; nothing about authorization changes here.
                logger.debug("Gateway bearer is not a platform token for RLS (request_id=%s)", request_id)
            else:
                _log_exception("Failed to decode token for RLS middleware (request_id=%s)", request_id)
        else:
            user_token = set_current_rls_user_id(user_id)

    try:
        response = await call_next(request)
        return response
    finally:
        if user_token is not None:
            reset_current_rls_user_id(user_token)
