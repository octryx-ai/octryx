"""Usage and transcript of one seat call, written after the response like the governed route."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....db import core as db_core
from ....models import ToolCall, TurnTrace, UsageEvent
from ....time_utils import utc_now
from ...agent_gateway.contract import TOOL_CALL_SOURCE_GATEWAY
from ...budget.api_equivalent import api_equivalent_usd, stored
from ...observability import agent_metrics
from ...observability.run_capture import capture_mode, gateway_capture
from ...observability.run_summary import gateway_run_summary, summary_row
from ...redaction_policy import redact_secret_text
from .anthropic_stream import Observation
from .transcript_messages import (
    MAX_ASSISTANT_CHARS,
    delta_summary,
    link_answer_trace,
    record_turn_messages,
)
from .transcript_tools import upsert_gateway_tool_calls
from .turn_delta import newest_turn

logger = logging.getLogger(__name__)

SEAT_DISPATCH_OWNER = "model_gateway_inbound_anthropic_seat"
SEAT_PROVIDER = "anthropic_seat"
SEAT_COST_SOURCE = "seat_subscription"
SEAT_COST_STATUS = "not_billed_to_platform"


@dataclass(frozen=True, slots=True)
class SeatCallRecord:
    session_id: str
    user_id: str
    model: str
    body: Mapping[str, Any]
    observation: Observation
    upstream_request_id: str
    duration_ms: int
    status_code: int
    client_context: Mapping[str, str] = field(default_factory=dict)
    # The Codex seat (``codex_seat``) records under its own provider and owner; the body is then the Anthropic-shaped
    # view of its Responses request (``openai_view``).
    provider: str = SEAT_PROVIDER
    dispatch_owner: str = SEAT_DISPATCH_OWNER


def _usage_event(record: SeatCallRecord, model: str) -> UsageEvent:
    usage = record.observation.usage
    return UsageEvent(
        id=str(uuid.uuid4()),
        session_id=record.session_id,
        user_id=record.user_id,
        provider=record.provider,
        model=model,
        tokens_in=int(usage.get("input_tokens") or 0),
        tokens_out=int(usage.get("output_tokens") or 0),
        cache_read_tokens=usage.get("cache_read_input_tokens"),
        cache_creation_tokens=usage.get("cache_creation_input_tokens"),
        cost=Decimal("0"),
        # What the call would have cost through the API, shown apart from ``cost``.
        list_cost=stored(api_equivalent_usd(model, usage)),
        cost_source=SEAT_COST_SOURCE,
        cost_status=SEAT_COST_STATUS,
        request_id=record.upstream_request_id[:64] or None,
        dispatch_owner=record.dispatch_owner,
    )


def _usage_json(record: SeatCallRecord, model: str) -> dict[str, Any]:
    observation = record.observation
    return {
        **observation.usage,
        "cost": 0.0,
        "cost_source": SEAT_COST_SOURCE,
        "cost_status": SEAT_COST_STATUS,
        "model": model,
        "stop_reason": observation.stop_reason,
        "stream_completed": observation.stream_completed,
        "duration_ms": record.duration_ms,
        "upstream_status": record.status_code,
        "upstream_error_type": observation.upstream_error_type,
        "gateway_evidence": {"dispatch_owner": record.dispatch_owner, "profile": "seat"},
    }


async def _write(db: AsyncSession, record: SeatCallRecord) -> None:
    observation = record.observation
    model = record.model[:100]
    db.add(_usage_event(record, model))
    delta = newest_turn(record.body.get("messages"))
    raw_output = {
        "text": redact_secret_text(observation.text, max_chars=MAX_ASSISTANT_CHARS),
        "tool_uses": list(observation.tool_uses),
        "stop_reason": observation.stop_reason,
    }
    usage_json = _usage_json(record, model)
    trace = TurnTrace(
        id=str(uuid.uuid4()),
        session_id=record.session_id,
        provider=record.provider,
        model=model,
        **gateway_capture(await capture_mode(db, record.session_id), input_messages=delta_summary(delta),
                          context_snapshot={"source": TOOL_CALL_SOURCE_GATEWAY, "profile": "seat",
                                            **dict(record.client_context)},
                          raw_output=raw_output),
        usage_json=usage_json,
        created_at=utc_now(),
    )
    db.add(trace)
    db.add(summary_row(trace, gateway_run_summary(
        session_id=record.session_id, raw_output=raw_output, usage=usage_json,
        duration_ms=record.duration_ms, client_context=record.client_context, seat=True,
    )))
    if 200 <= record.status_code < 300:
        await upsert_gateway_tool_calls(db, record.session_id, delta)
        for search in observation.hosted_searches:
            db.add(hosted_search_row(record.session_id, search))
        await link_answer_trace(db, trace, await record_turn_messages(
            db, session_id=record.session_id, body=record.body, observation=observation, delta=delta,
            model=model, cost=Decimal("0"),
        ))


HOSTED_SEARCH_TOOL = "codex_hosted_web_search"


def hosted_search_row(session_id: str, search: Mapping[str, str]) -> ToolCall:
    completed = search.get("status") == "completed"
    return ToolCall(session_id=session_id, tool_name=HOSTED_SEARCH_TOOL, status="success" if completed else "error",
                    parameters={"source": TOOL_CALL_SOURCE_GATEWAY, "hosted": True, "item_id": search.get("id"),
                                "action": search.get("action"), "target": search.get("target")},
                    result={"is_error": not completed, "status": search.get("status")}, created_at=utc_now())


async def record_seat_call(record: SeatCallRecord) -> bool:
    try:
        seconds = record.duration_ms / 1000 if record.duration_ms else None
        with agent_metrics.seat_call(agent_metrics.ROUTE_GATEWAY, seconds):
            async with db_core.async_session_factory() as db:
                await _write(db, record)
                await db.commit()
        return True
    except Exception as exc:  # noqa: BLE001 - recording must not break the relayed response
        logger.error("Seat gateway call record failed (error_class=%s)", type(exc).__name__)
        return False


__all__ = ["SEAT_COST_SOURCE", "SEAT_DISPATCH_OWNER", "SEAT_PROVIDER", "SeatCallRecord", "record_seat_call"]
