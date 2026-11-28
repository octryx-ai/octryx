"""Usage and transcript of one inbound model call, recorded after the response in a fresh database session."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....db import core as db_core
from ....models import TurnTrace, UsageEvent
from ....time_utils import utc_now
from ...agent_gateway.contract import TOOL_CALL_SOURCE_GATEWAY
from ...observability.run_capture import capture_mode, gateway_capture
from ...observability.run_summary import gateway_run_summary, summary_row
from ...redaction_policy import redact_secret_text
from ..litellm.alias_catalog import AliasEntry
from .admission import INBOUND_DISPATCH_OWNER
from .anthropic_stream import Observation
from .transcript_cost import UsageCost, usage_cost
from .transcript_messages import MAX_ASSISTANT_CHARS, delta_summary, link_answer_trace, record_turn_messages
from .transcript_tools import upsert_gateway_tool_calls
from .turn_delta import TurnDelta, newest_turn

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GatewayCallRecord:
    session_id: str
    user_id: str
    provider_name: str
    entry: AliasEntry
    body: Mapping[str, Any]
    observation: Observation
    upstream_request_id: str
    duration_ms: int
    evidence: Mapping[str, Any]
    client_context: Mapping[str, str] = field(default_factory=dict)
    refused_reason: str = ""


async def _record_messages(
    db: AsyncSession, record: GatewayCallRecord, delta: TurnDelta, cost: UsageCost
) -> str | None:
    return await record_turn_messages(
        db, session_id=record.session_id, body=record.body, observation=record.observation, delta=delta,
        model=record.entry.alias, cost=cost.cost,
    )


def _usage_event(record: GatewayCallRecord, cost: UsageCost) -> UsageEvent:
    usage = record.observation.usage
    return UsageEvent(
        id=str(uuid.uuid4()),
        session_id=record.session_id,
        user_id=record.user_id,
        provider=record.provider_name[:100],
        model=record.entry.alias[:100],
        tokens_in=int(usage.get("input_tokens") or 0),
        tokens_out=int(usage.get("output_tokens") or 0),
        cache_read_tokens=usage.get("cache_read_input_tokens"),
        cache_creation_tokens=usage.get("cache_creation_input_tokens"),
        cost=cost.cost,
        cost_source=cost.cost_source or None,
        cost_status=cost.cost_status[:64] or None,
        request_id=record.upstream_request_id[:64] or None,
        dispatch_owner=INBOUND_DISPATCH_OWNER,
    )


def _raw_output(observation: Observation) -> dict[str, Any]:
    return {
        "text": redact_secret_text(observation.text, max_chars=MAX_ASSISTANT_CHARS),
        "tool_uses": list(observation.tool_uses),
        "stop_reason": observation.stop_reason,
    }


def _usage_json(record: GatewayCallRecord, cost: UsageCost) -> dict[str, Any]:
    observation = record.observation
    return {
        **observation.usage,
        "cost": float(cost.cost),
        "cost_source": cost.cost_source,
        "cost_status": cost.cost_status,
        "alias": record.entry.alias,
        "stop_reason": observation.stop_reason,
        "stream_completed": observation.stream_completed,
        "duration_ms": record.duration_ms,
        "model_match": observation.model_match,
        "upstream_error_type": observation.upstream_error_type,
        "refused_reason": record.refused_reason,
        "gateway_evidence": dict(record.evidence),
    }


async def _write(db: AsyncSession, record: GatewayCallRecord) -> None:
    observation = record.observation
    cost = usage_cost(record.entry, observation.usage)
    db.add(_usage_event(record, cost))
    delta = newest_turn(record.body.get("messages"))
    raw_output = _raw_output(observation)
    usage_json = _usage_json(record, cost)
    trace = TurnTrace(
        id=str(uuid.uuid4()),
        session_id=record.session_id,
        provider=record.provider_name[:100],
        model=record.entry.alias[:100],
        # The Workspace capture policy applies here too.
        **gateway_capture(await capture_mode(db, record.session_id), input_messages=delta_summary(delta),
                          context_snapshot={"source": TOOL_CALL_SOURCE_GATEWAY, **dict(record.client_context)},
                          raw_output=raw_output),
        usage_json=usage_json,
        created_at=utc_now(),
    )
    db.add(trace)
    db.add(summary_row(trace, gateway_run_summary(
        session_id=record.session_id, raw_output=raw_output, usage=usage_json,
        duration_ms=record.duration_ms, client_context=record.client_context,
    )))
    if not record.refused_reason:
        await upsert_gateway_tool_calls(db, record.session_id, delta)
        await link_answer_trace(db, trace, await _record_messages(db, record, delta, cost))


# A usage-contract violation is recorded at cost 0 with that status: the answer was already served.
async def record_gateway_call(record: GatewayCallRecord) -> bool:
    try:
        async with db_core.async_session_factory() as db:
            await _write(db, record)
            await db.commit()
        return True
    except Exception as exc:  # noqa: BLE001 - recording must not break the relayed response
        logger.error("Model gateway call record failed (error_class=%s)", type(exc).__name__)
        return False


__all__ = [
    "GatewayCallRecord",
    "record_gateway_call",
]
