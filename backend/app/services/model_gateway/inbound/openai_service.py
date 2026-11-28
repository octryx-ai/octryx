"""The inbound OpenAI Responses gateway for Codex (POST /api/v1/model-gateway/openai/v1/responses)."""

from __future__ import annotations

import functools
import time
from collections.abc import Mapping
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent_gateway.contract import STATE_DENIED
from ...agent_gateway.engine_keys import ENGINE_CODEX, REASON_ENGINE_NOT_ALLOWED
from ...agent_gateway.engine_policy import effective_engine
from ...agent_gateway.identity import GatewayIdentity
from ...content_routing.gateway_outcome import STAGE_BUDGET, GatewayOutcome, gateway_outcome, recorded
from .admission import InboundAdmission
from .anthropic_stream import Observation
from .call_context import client_context
from .governed_dispatch import budget_refusal, upstream_refusal, with_notice
from .model_routes import governed_models
from .openai_view import anthropic_view, is_responses_body
from .refusals import InboundRefusal, openai_error_response, refusal
from .relay import relay_json, relay_stream
from .responses_namespaces import NamespaceMap, flatten_request
from .responses_stream import (
    KEEPALIVE_COMMENT,
    REASON_MISSING_RESPONSE_CREATED,
    ResponsesSseRelay,
    relay_json_response,
)
from .service import admitted_request, governed_plan, log_context_size
from .transcript import GatewayCallRecord
from .upstream import RESPONSES_PATH, build_upstream_client, send_upstream

# Codex's own correlation headers on a Responses call (codex-rs ``codex-api``: ``build_session_headers`` sets
# ``session-id`` / ``thread-id``, ``ResponsesClient`` sets ``x-openai-subagent`` for review/compact sub-agents).
CODEX_CONTEXT_HEADERS = {
    "session-id": "codex_session_id",
    "thread-id": "codex_thread_id",
    "x-openai-subagent": "codex_subagent",
}
BODY_INVALID_HINT = "The request body is not a valid OpenAI Responses request."
OWNED_BY = "octryx"
_ENGINE_HINT = "Codex is not allowed in this Workspace; a Workspace admin can allow it under the coding engines."


def _refused(item: InboundRefusal) -> Response:
    return openai_error_response(item)


@recorded
async def handle_responses(request: Request, db: AsyncSession) -> Response:
    resolved = await admitted_request(request, db, render=openai_error_response, valid=is_responses_body,
                                      invalid_hint=BODY_INVALID_HINT)
    if isinstance(resolved, Response):
        return resolved
    identity, session_id, body, admitted = resolved
    # Only Codex speaks this route: a Workspace that does not allow Codex (``agent_gateway.engines``) refuses it.
    engine = await effective_engine(db, user_id=identity.user.id, workspace_id=identity.workspace_id)
    if ENGINE_CODEX not in engine.allowed:
        return _refused(refusal(STATE_DENIED, REASON_ENGINE_NOT_ALLOWED, http_status=403, hint=_ENGINE_HINT))
    # The run's budget (and Codex's own model ceiling) on the governed Codex route too; never a Claude model here.
    from .run_limits import run_limited_body

    limited = await run_limited_body(db, session_id, dict(body), engine="codex")
    if isinstance(limited, InboundRefusal):
        return _refused(limited)
    # Codex's namespace tools as plain function tools (``responses_namespaces``): the content decision reads the
    # body that is forwarded, flat names included.
    flattened, names = flatten_request(limited)
    view = anthropic_view(limited)
    log_context_size(view, session_id=session_id)
    plan, admitted = await governed_plan(db, request=request, identity=identity, session_id=session_id,
                                         admitted=admitted, build=lambda target: responses_payload(flattened, target))
    if plan.refusal is not None:
        return _refused(plan.refusal)
    outcome = gateway_outcome(request)
    budget = await budget_refusal(db, identity=identity, session_id=session_id, body=view, admitted=admitted)
    if budget is not None:
        return _refused(outcome.stopped(budget, STAGE_BUDGET))
    return await _dispatch(request.headers, identity=identity, session_id=session_id, payload=plan.payload,
                           stream=flattened.get("stream") is True, names=names, view=view, admitted=admitted,
                           outcome=outcome)


LOCAL_MIN_OUTPUT_TOKENS = 8192
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "host.docker.internal"})


def local_upstream(base_url: object) -> bool:
    from urllib.parse import urlsplit

    host = (urlsplit(str(base_url or "")).hostname or "").lower()
    return host in _LOCAL_HOSTS or host.endswith(".local")


# The alias' answer budget when the client sends none (Codex never does), at least the floor a local reasoning model
# needs (it stops mid-thought below about 8k).
def responses_payload(flattened: Mapping[str, Any], admitted: InboundAdmission) -> dict[str, Any]:
    payload = dict(flattened)
    if "max_output_tokens" not in payload and admitted.entry.max_output_tokens:
        payload["max_output_tokens"] = admitted.entry.max_output_tokens
    if local_upstream(admitted.config.endpoint.base_url):
        given = payload.get("max_output_tokens")
        if not isinstance(given, int) or given < LOCAL_MIN_OUTPUT_TOKENS:
            payload["max_output_tokens"] = LOCAL_MIN_OUTPUT_TOKENS
    return {**payload, "model": admitted.entry.model_group}


async def _dispatch(
    headers: Mapping[str, str], *, identity: GatewayIdentity, session_id: str, payload: bytes, stream: bool,
    names: NamespaceMap, view: Mapping[str, Any], admitted: InboundAdmission, outcome: GatewayOutcome,
) -> Response:
    context = client_context(headers, CODEX_CONTEXT_HEADERS)

    def make_record(observation: Observation, request_id: str, duration_ms: int, refused: str) -> GatewayCallRecord:
        return GatewayCallRecord(
            session_id=session_id, user_id=identity.user.id, provider_name=admitted.provider_name,
            entry=admitted.entry, body=view, observation=observation, upstream_request_id=request_id,
            duration_ms=duration_ms, evidence=admitted.evidence, client_context=context, refused_reason=refused,
        )

    client = build_upstream_client(admitted.config)
    started = time.perf_counter()
    # ``headers={}``: nothing of the client request travels upstream (its Authorization is the platform token).
    upstream = await send_upstream(client, path=RESPONSES_PATH, body=payload, headers={}, received=outcome.received)
    if isinstance(upstream, InboundRefusal):
        await client.aclose()
        return with_notice(_refused(upstream_refusal(outcome, upstream)), outcome)
    observation = Observation()
    if stream:
        relay = ResponsesSseRelay(entry=admitted.entry, observation=observation, names=names)
        response = await relay_stream(upstream, client, relay, started=started, make_record=make_record,
                                      render=openai_error_response, keepalive=KEEPALIVE_COMMENT,
                                      missing_start_reason=REASON_MISSING_RESPONSE_CREATED)
    else:
        response = await relay_json(upstream, client, observation, entry=admitted.entry, started=started,
                                    make_record=make_record, render=openai_error_response,
                                    answer=functools.partial(relay_json_response, names=names))
    return with_notice(response, outcome)


async def handle_openai_list_models(request: Request, db: AsyncSession) -> Response:
    models = await governed_models(request, db, render=openai_error_response)
    if isinstance(models, Response):
        return models
    return JSONResponse({"object": "list", "data": [
        {"id": model.id, "object": "model", "owned_by": OWNED_BY, "display_name": model.display_name,
         "description": model.description} for model in models]})


__all__ = [
    "CODEX_CONTEXT_HEADERS",
    "handle_openai_list_models",
    "handle_responses",
    "responses_payload",
]
