"""The inbound OpenAI Responses gateway for Codex (``POST /api/v1/model-gateway/openai/v1/responses``).

Codex (``wire_api = "responses"``) started through the launcher points its provider ``base_url`` at
``<platform>/api/v1/model-gateway/openai/v1``. A call runs the Anthropic route's pipeline (``service``) in the
same order, with the same refusals and reasons, only in the OpenAI error shape:

0. (after step 1) the Workspace must allow the Codex engine (``agent_gateway.engines``), else
   ``denied/engine_not_allowed_in_workspace``;
1. gateway identity, shadow session, bounded body read (a Responses body: ``model`` and ``input``), presence,
   admission (``declares_tools`` from ``tools``), the phase agent's model and the device-loop guard
   (``service.admitted_request``);
2. content governance on the payload that is sent (namespace tools flattened, ``responses_namespaces``; model and
   output cap as in step 4): the gateway's content decision (``content_routing.gateway_plan``: the whole payload
   read as one text, each tool output as one text) — the fixed rules, the Workspace's content handling (``secrets``
   and ``credential_assignment``: ``refuse`` or ``report``) and Cedar, exactly as for a Messages call. It refuses or
   the payload goes on unchanged; the Anthropic-shaped view (``openai_view``) never decides, it is only the budget
   estimate, the context-size log and the transcript;
3. the daily and platform budgets on the view (``service.budget_refusal``);
4. dispatch to LiteLLM's ``/v1/responses`` of exactly the payload the content decision read: the flattened body
   with ``model`` replaced by the alias' model group and the effective output cap (:func:`responses_payload`,
   built before the scan). No client header is forwarded; the virtual key is the only credential (``upstream``);
5. the relay (``responses_stream``), which checks the served model, rewrites it to the alias, replaces upstream
   errors with fixed text and records usage, cost and transcript like the Anthropic route.

``GET .../v1/models`` lists what the Workspace admits (``model_routes.governed_models``) in the OpenAI list shape.
"""

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
from .service import admitted_request, content_plan, log_context_size
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
    plan = await content_plan(db, request=request, body=responses_payload(flattened, admitted), identity=identity,
                              admitted=admitted)
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
    """A model served on this machine (llama.cpp and the like), not a provider or a company gateway."""
    from urllib.parse import urlsplit

    host = (urlsplit(str(base_url or "")).hostname or "").lower()
    return host in _LOCAL_HOSTS or host.endswith(".local")


def responses_payload(flattened: Mapping[str, Any], admitted: InboundAdmission) -> dict[str, Any]:
    """The payload a governed Responses call sends (and the content decision reads): the flattened body with the
    alias' answer budget when the client sends none (Codex never does), the floor of a local reasoning model (it
    stops mid-thought below about 8k) and ``model`` replaced by the alias' model group."""
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
    """``payload`` (the plan's bytes of the scanned payload; ``names`` restores the answer's calls) to the admitted
    alias."""
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
    """The Workspace's admitted aliases in the OpenAI list shape (no ``created``: an alias has no release date)."""
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
