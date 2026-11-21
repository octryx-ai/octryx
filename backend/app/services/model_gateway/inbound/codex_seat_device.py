"""Codex seat calls sent from the device: the server admits, the Mac sends (``seat_traffic``).

The launcher's loopback seat proxy (``octryx_claude.codex_seat_proxy``) handles each Codex ``POST /responses`` in
three steps; both server steps authenticate exactly like the relay route (the session-bound seat credential and the
session headers Codex sends; never the ChatGPT ``Authorization`` or account id):

1. ``POST /api/v1/model-gateway/openai/seat/admit`` with Codex's request body: the relay route's own checks
   (:func:`codex_seat.admit_codex_seat`: seat identity and session, the Codex seat decision, the engine, the run's
   model guard and budget, ``codex_seat_models``, the gateway content decision). A refusal is
   the route's OpenAI-shaped error with the same status, which the proxy relays to Codex unchanged. Admitted:
   ``{body, ticket, notice, expires_in}`` (``codex_seat_tickets``: single use, 15 minutes, bound to session, user,
   admitted model and the admitted body's hash);
2. the proxy sends the admitted body to ``https://chatgpt.com/backend-api/codex/responses`` with the person's own
   login and streams the answer back to Codex byte for byte;
3. ``POST .../seat/report`` with the ticket, the admitted body, the answer's status, its relayed headers and the raw
   answer (bounded; ``truncated`` when cut). The server feeds it through the **same** observer and recorder as the
   route (``codex_seat_observer``, ``seat_transcript.record_seat_call``, ``parse_codex_allowance``), so usage,
   transcript, tool calls (and with them the exec evidence) and the allowance are written as for a relayed call.

Plausibility: the answer's model must be the admitted one, its response id new, its usage
numbers sane; a deviation is a ``seat_report_mismatch`` event (field names only) and the record carries the marks
(``usage_json.seat_report.mismatch``), never silently clean. A report with a missing, unknown, used, expired or
foreign ticket is refused (403) and writes nothing; a report whose body is not the admitted one is refused too and
leaves a mismatch event. A ticket without a report is found by the run sweep (``seat_call_without_report``). A
ticket admitted on the device's way is reported even when a platform admin switched to ``gateway`` meanwhile: the
call already left the device and is recorded.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from typing import Any

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent_gateway.allowance import parse_codex_allowance
from ...agent_gateway.contract import HEADER_GATEWAY_REASON, STATE_DENIED
from ...agent_gateway.engine_keys import ENGINE_CODEX
from ...agent_gateway.identity import GatewayIdentity, GatewayRefusal
from ...agent_gateway.presence import record_allowance
from ...agent_gateway.seat_credential import resolve_seat_identity
from ...agent_gateway.seat_traffic import SEAT_TRAFFIC_DEVICE
from ...agent_gateway.sessions import find_gateway_session
from ...content_routing.gateway_outcome import gateway_outcome, recorded
from ...observability import agent_metrics, attribution
from .anthropic_stream import Observation
from .call_context import client_context
from .codex_seat import (
    CODEX_SEAT_DISPATCH_OWNER,
    CODEX_SEAT_PROVIDER,
    admit_codex_seat,
    codex_seat_refused,
)
from .codex_seat_observer import CodexSeatObserver, observe_responses_body
from .codex_seat_tickets import (
    EVENT_REPORT_MISMATCH,
    TICKET_SECONDS,
    TicketClaim,
    body_sha256,
    claim_ticket,
    issue_ticket,
    seat_event,
    seen_response,
)
from .codex_seat_upstream import codex_seat_response_headers
from .openai_service import CODEX_CONTEXT_HEADERS
from .openai_view import anthropic_view
from .refusals import refusal
from .seat_transcript import SeatCallRecord, record_seat_call
from .service import MAX_REQUEST_BODY_BYTES

# The admitted body (bounded like any request) plus the answer the proxy observed (≤ 2 MB head and a tail).
MAX_REPORTED_ANSWER_BYTES = 4 * 1024 * 1024
MAX_REPORT_BYTES = MAX_REQUEST_BODY_BYTES + 2 * MAX_REPORTED_ANSWER_BYTES
MAX_SANE_TOKENS = 50_000_000
MAX_DURATION_MS = 24 * 3600 * 1000
REASON_REPORT_INVALID = "seat_report_invalid"
REASON_REPORT_TOO_LARGE = "seat_report_too_large"
REASON_BODY_MISMATCH = "seat_ticket_body_mismatch"
SEAT_TRAFFIC_EVIDENCE = "seat_traffic"


@recorded
async def handle_codex_seat_admit(request: Request, db: AsyncSession) -> Response:
    admitted = await admit_codex_seat(request, db, device=True)
    if isinstance(admitted, Response):
        agent_metrics.record_seat_admit(ENGINE_CODEX, "refused", admitted.headers.get(HEADER_GATEWAY_REASON, ""))
        return admitted
    codex_session = str(request.headers.get("session-id") or request.headers.get("session_id") or "")
    ticket = await issue_ticket(db, session_id=admitted.session_id, user_id=admitted.identity.user.id,
                                model=admitted.body["model"].strip(), body=admitted.body,
                                codex_session_id=codex_session)
    await db.commit()
    notice = await gateway_outcome(request).sent()  # handed to the device, which sends the body it posted
    agent_metrics.record_seat_admit(ENGINE_CODEX, "admitted")
    return JSONResponse({"body": admitted.body, "ticket": ticket, "notice": notice,
                         "expires_in": TICKET_SECONDS})


async def _report_payload(request: Request) -> dict[str, Any] | str:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_REPORT_BYTES:
        return REASON_REPORT_TOO_LARGE
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_REPORT_BYTES:
            return REASON_REPORT_TOO_LARGE
    try:
        payload = json.loads(bytes(raw))
    except ValueError:
        return REASON_REPORT_INVALID
    status = payload.get("status_code") if isinstance(payload, dict) else None
    if (not isinstance(payload, dict) or not isinstance(payload.get("body"), dict)
            or type(status) is not int or not 0 <= status <= 599):
        return REASON_REPORT_INVALID
    return payload


def _answer(payload: Mapping[str, Any]) -> tuple[bytes, bool] | None:
    """The reported raw answer (``response_b64``), bounded; ``None`` when not decodable."""
    try:
        raw = base64.b64decode(str(payload.get("response_b64") or ""), validate=True)
    except (binascii.Error, ValueError):
        return None
    truncated = payload.get("truncated") is True or len(raw) > MAX_REPORTED_ANSWER_BYTES
    return raw[:MAX_REPORTED_ANSWER_BYTES], truncated


def _model_matches(admitted: str, answered: str) -> bool:
    """The answer's model is the admitted one (or its dated snapshot, ``<model>-2026-…``); unknown is not checked."""
    return not answered or answered == admitted or answered.startswith(admitted + "-")


def _sane_usage(observation: Observation) -> bool:
    """Every usage number non-negative and bounded; an insane one is clamped (and the record marked)."""
    sane = True
    for key, value in list(observation.usage.items()):
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_SANE_TOKENS:
            sane = False
            observation.usage[key] = min(max(int(value) if isinstance(value, int) else 0, 0), MAX_SANE_TOKENS)
    return sane


def _observe(observation: Observation, raw: bytes, *, streamed: bool, complete: bool) -> tuple[str, str]:
    """The route's own observation of the answer; returns the answer's (response id, model)."""
    if not streamed:
        try:
            parsed = json.loads(raw)
        except ValueError:
            return "", ""
        observe_responses_body(observation, parsed)
        if not isinstance(parsed, Mapping):
            return "", ""
        return str(parsed.get("id") or "")[:200], str(parsed.get("model") or "")[:200]
    observer = CodexSeatObserver(observation)
    observer.feed(raw)
    if complete:
        observer.finish()  # the route finishes only a stream it read to the end
    return observer.response_id, observer.response_model


def _refused(reason: str, status: int = 403) -> Response:
    return codex_seat_refused(refusal(STATE_DENIED, reason, http_status=status))


async def _mismatch(db: AsyncSession, claim: TicketClaim, fields: list[str]) -> None:
    await seat_event(db, run_id=claim.run_id, session_id=claim.session_id, user_id=claim.user_id,
                     kind=EVENT_REPORT_MISMATCH, detail={"fields": fields, "model": claim.model})


def _reported_seconds(payload: Mapping[str, Any]) -> float | None:
    """The call's duration the device measured (``duration_ms``), in seconds; ``None`` when it sent none."""
    duration = payload.get("duration_ms")
    return min(max(duration, 0), MAX_DURATION_MS) / 1000 if type(duration) is int else None

async def handle_codex_seat_report(request: Request, db: AsyncSession) -> Response:
    identity = await resolve_seat_identity(db, request.headers)
    if isinstance(identity, GatewayRefusal):
        return codex_seat_refused(identity)
    session = await find_gateway_session(db, identity)
    if isinstance(session, GatewayRefusal):
        return codex_seat_refused(session)
    payload = await _report_payload(request)
    if isinstance(payload, str):
        return _refused(payload, 413 if payload == REASON_REPORT_TOO_LARGE else 400)
    answer = _answer(payload)
    if answer is None:
        return _refused(REASON_REPORT_INVALID, 400)
    claim = await claim_ticket(db, payload.get("ticket"), session_id=session.id, user_id=identity.user.id)
    if isinstance(claim, str):
        return _refused(claim)
    body, status = payload["body"], int(payload["status_code"])
    if body_sha256(body) != claim.body_sha256:
        await _mismatch(db, claim, ["body"])
        await db.commit()
        return _refused(REASON_BODY_MISMATCH)
    if status == 0:  # no upstream answer (unreachable, timeout): nothing to record, like the route
        await db.commit()
        return JSONResponse({"recorded": False, "mismatch": []})
    headers = {str(name).lower(): str(value) for name, value in dict(payload.get("headers") or {}).items()}
    await record_allowance(db, identity.session_key, parse_codex_allowance(headers), engine="codex")
    if status >= 300:  # an upstream error: relayed, not recorded (the route's rule)
        await db.commit()
        agent_metrics.record_seat_upstream_error(CODEX_SEAT_PROVIDER, claim.model, agent_metrics.ROUTE_DEVICE_REPORT,
                                                 _reported_seconds(payload))
        return JSONResponse({"recorded": False, "mismatch": []})
    return await _record_report(request, db, identity=identity, session_id=session.id, claim=claim, payload=payload,
                                headers=headers, answer=answer)


async def _record_report(
    request: Request, db: AsyncSession, *, identity: GatewayIdentity, session_id: str, claim: TicketClaim,
    payload: Mapping[str, Any], headers: dict[str, str], answer: tuple[bytes, bool],
) -> Response:
    """Observe, check and record a reported answer the upstream accepted (status below 300)."""
    body, status = payload["body"], int(payload["status_code"])
    raw, truncated = answer
    observation = Observation()
    streamed = body.get("stream") is True
    response_id, model = _observe(observation, raw, streamed=streamed, complete=payload.get("complete") is True)
    mismatch = [] if _model_matches(claim.model, model) else ["model"]
    if response_id and await seen_response(db, response_id, session_id=session_id):
        mismatch.append("response_id")
    if not _sane_usage(observation):
        mismatch.append("usage")
    if mismatch:
        await _mismatch(db, claim, mismatch)
    await db.commit()
    relayed = codex_seat_response_headers(httpx.Headers(headers))
    duration = payload.get("duration_ms")
    # The ticket's run labels the tokens. A run-bound session's request already carries "run" in its
    # attribution; passing it twice raises a TypeError, every report answers 500, no seat call is recorded and
    # none of the Codex exec calls count as evidence.
    labels = {**(attribution.current() or {})}
    if claim.run_id:
        labels["run"] = claim.run_id
    with attribution.scope(**labels):
        recorded = await record_seat_call(SeatCallRecord(
            session_id=session_id, user_id=identity.user.id, model=claim.model, body=anthropic_view(body),
            observation=observation,
            upstream_request_id=relayed.get("x-request-id", "") or relayed.get("x-oai-request-id", ""),
            duration_ms=min(max(duration, 0), MAX_DURATION_MS) if type(duration) is int else 0, status_code=status,
            client_context=client_context(request.headers, CODEX_CONTEXT_HEADERS), provider=CODEX_SEAT_PROVIDER,
            dispatch_owner=CODEX_SEAT_DISPATCH_OWNER,
            evidence={SEAT_TRAFFIC_EVIDENCE: SEAT_TRAFFIC_DEVICE,
                      "seat_report": {"mismatch": mismatch, "truncated": truncated}},
        ))
    return JSONResponse({"recorded": recorded, "mismatch": mismatch})


__all__ = [
    "MAX_REPORTED_ANSWER_BYTES",
    "REASON_BODY_MISMATCH",
    "handle_codex_seat_admit",
    "handle_codex_seat_report",
]
