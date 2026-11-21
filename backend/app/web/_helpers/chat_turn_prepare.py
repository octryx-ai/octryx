"""``/chat/api`` HTTP adapter of turn preparation (``services/session/turn_start``).

The service owner answers a closed :class:`TurnRefusal`; this adapter keeps the chat HTTP
contract: the shared status (``REFUSAL_HTTP_STATUS``) with the plain detail the chat UI
always received. :func:`chat_turn_request` builds the owner's request from the chat
routes' keyword arguments.

No chat route can make ``agent_type`` a decision: the chat request has no such field, the
route passes the platform or session mode and the owner's request is never
``agent_type_explicit``.
"""

from fastapi import HTTPException

from ...services.agent_mode import DEFAULT_AGENT_MODE_KEY
from ...services.session.turn_refusals import TurnRefusal
from ...services.session.turn_request import TurnRequest

__all__ = [
    "chat_refusal_http_exception",
    "chat_turn_request",
]


def chat_refusal_http_exception(refusal: TurnRefusal) -> HTTPException:
    return HTTPException(status_code=refusal.http_status, detail=refusal.detail)


def chat_turn_request(
    *,
    user_id: str,
    prompt: str,
    session_id: str | None = "",
    project_id: str | None = "",
    runtime_target_id: str | None = "",
    agent_id: str | None = "",
    agent_type: str = DEFAULT_AGENT_MODE_KEY,
    workflow_key: str = "",
    workflow_decisions: dict[str, str] | None = None,
    project_id_explicit: bool = False,
    runtime_target_id_explicit: bool = False,
    thinking_level_explicit: bool = False,
    thinking_level: str = "light",
    idempotency_key: str | None = None,
    session_metadata_patch: dict | None = None,
) -> TurnRequest:
    return TurnRequest(
        user_id=user_id,
        prompt=prompt,
        session_id=session_id or "",
        project_id=project_id or "",
        runtime_target_id=runtime_target_id or "",
        agent_id=agent_id or "",
        agent_type=agent_type,
        workflow_key=workflow_key or "",
        workflow_decisions=workflow_decisions,
        agent_type_explicit=False,
        project_id_explicit=project_id_explicit,
        runtime_target_id_explicit=runtime_target_id_explicit,
        thinking_level_explicit=thinking_level_explicit,
        thinking_level=thinking_level,
        idempotency_key=idempotency_key,
        session_metadata_patch=session_metadata_patch or {},
    )

