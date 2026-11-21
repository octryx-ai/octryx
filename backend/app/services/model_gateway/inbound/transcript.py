"""Usage and transcript of one inbound model call, written after the response.

Runs in a fresh database session (the request-scoped one may already be closed
while a stream is relayed) and records what was *observed*, including partial
streams (``stream_completed`` says which):

- one ``UsageEvent``: ``tokens_in`` = ``input_tokens``; cache reads and cache
  writes in their own columns. The cost follows the alias' governed cost
  contract through ``resolve_usage_payload`` with *all* prompt tokens (input +
  cache creation + cache read), so pricing matches the internal driver path.
  A usage contract violation is recorded at cost 0 with that violation as the
  ``cost_status`` — the answer was already served, so it cannot be discarded;
- one ``TurnTrace``: only the newest turn (bounded, redacted), the assistant
  text and ``tool_use`` summary, usage and closed gateway evidence;
- ``ToolCall`` rows per the agent-gateway contract: ``tool_use`` blocks of the
  assistant message before the trailing user message are upserted as
  ``requested`` (one row per ``tool_use`` id, idempotent on client retries), and
  ``tool_result`` blocks of the trailing user message set ``result`` and
  ``success``/``error`` from ``is_error``. A row the execution-evidence hook
  created first (``agent_gateway/tool_execution.py``) is completed, never
  replaced. Rows written by the client hooks (``source=client_hook``) are never
  touched;
- ``Message`` rows only for agent-loop calls, defined structurally as requests
  that declare ``tools`` (Claude Code's utility calls — titles, summaries — carry
  none): the user's prompt when the trailing user message has text blocks other
  than ``<system-reminder>`` blocks, and the assistant's final text when the
  stop reason is ``end_turn``. The prompt is keyed by conversation position and
  content hash, so a retried call does not record it twice.

Every text is redacted with the shared redaction policy and bounded.
"""

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
    # Runs: the summary row of this call.
    db.add(summary_row(trace, gateway_run_summary(
        session_id=record.session_id, raw_output=raw_output, usage=usage_json,
        duration_ms=record.duration_ms, client_context=record.client_context,
    )))
    if not record.refused_reason:
        await upsert_gateway_tool_calls(db, record.session_id, delta)
        await link_answer_trace(db, trace, await _record_messages(db, record, delta, cost))


async def record_gateway_call(record: GatewayCallRecord) -> bool:
    """Persist one call; never raises into the response path."""

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
