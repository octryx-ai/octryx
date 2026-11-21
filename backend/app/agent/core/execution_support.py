"""Execution and persistence helpers shared by the agent engine."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import async_session_factory
from ...models import UsageEvent
from ...services.budget import UsageCostAttribution, compute_usage_event_cost_attribution
from ...services.budget.prompt_cache_charge import converse_prompt_split
from ...services.db_concurrency_observability import record_db_concurrency_event
from ...services.model_gateway.dispatch_owners import dispatch_owner as registered_dispatch_owner
from ...services.request_context import get_current_request_id

logger = logging.getLogger(__name__)


def _safe_usage_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _usage_prompt_tokens(usage_payload: dict[str, Any]) -> int:
    prompt_tokens = _safe_usage_int(usage_payload.get("prompt_tokens"))
    bedrock_total = _safe_usage_int(usage_payload.get("bedrock_total_input_tokens"))
    bedrock_components = (
        _safe_usage_int(usage_payload.get("inputTokens"))
        + _safe_usage_int(usage_payload.get("cacheReadInputTokens"))
        + _safe_usage_int(usage_payload.get("cacheWriteInputTokens"))
    )
    return max(prompt_tokens, bedrock_total, bedrock_components)


def _is_sqlite_lock_error(exc: Exception) -> bool:
    return "database is locked" in str(exc).lower()


@dataclass(kw_only=True)
class _UsageEventDraft:
    """The values of one usage event, before it is attributed and written."""

    session_id: str
    user_id: str
    provider: str
    model: str
    usage_payload: dict[str, Any]
    tokens_in: int
    tokens_out: int
    cache_read_tokens: int | None
    cache_creation_tokens: int | None
    request_id: str | None
    owner_key: str | None
    agent_chain_id: str | None
    flow_definition_id: str | None
    driver: str | None

    def new_event(self) -> UsageEvent:
        return UsageEvent(
            id=str(uuid.uuid4()),
            session_id=self.session_id,
            user_id=self.user_id,
            provider=self.provider,
            model=self.model,
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            cache_read_tokens=self.cache_read_tokens,
            cache_creation_tokens=self.cache_creation_tokens,
            request_id=self.request_id or get_current_request_id(),
            dispatch_owner=self.owner_key,
            agent_chain_id=self.agent_chain_id,
            flow_definition_id=self.flow_definition_id,
        )

    async def attribute(self, attribution_db: AsyncSession) -> UsageCostAttribution:
        # One attribution per event. The governed cost source and the accounting
        # status are persisted alongside the amount so a zero cost stays
        # auditable instead of ambiguous.
        return await compute_usage_event_cost_attribution(
            attribution_db,
            provider=self.provider,
            model=self.model,
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            usage=self.usage_payload,
            driver=self.driver,
            cache_read_tokens=self.cache_read_tokens or 0,
            cache_creation_tokens=self.cache_creation_tokens or 0,
        )


def _apply_attribution(event: UsageEvent, attribution: UsageCostAttribution) -> None:
    event.cost = attribution.cost
    event.cost_source = attribution.cost_source or None
    event.cost_status = attribution.status


def _log_foreign_key_race(session_id: str) -> None:
    logger.debug(
        "Skipping usage event persistence for session %s after foreign-key visibility race",
        session_id,
        exc_info=True,
    )


def _log_unexpected_error(session_id: str) -> None:
    logger.warning(
        "Skipping usage event persistence for session %s after unexpected error",
        session_id,
        exc_info=True,
    )


async def _persist_in_session(db: AsyncSession, draft: _UsageEventDraft, usage_event: UsageEvent) -> None:
    """Write the event in the caller's session; any database failure skips it instead of failing the turn."""
    session_id = draft.session_id
    try:
        _apply_attribution(usage_event, await draft.attribute(db))
        db.add(usage_event)
        await db.flush()
    except OperationalError as exc:
        if _is_sqlite_lock_error(exc):
            record_db_concurrency_event("usage_event", "sqlite_lock_skipped")
            logger.warning(
                "Skipping usage event persistence for session %s after database lock",
                session_id,
                exc_info=exc,
            )
            return
        logger.warning(
            "Skipping usage event persistence for session %s after unexpected database error",
            session_id,
            exc_info=exc,
        )
    except IntegrityError:
        _log_foreign_key_race(session_id)
    except (SQLAlchemyError, TypeError, ValueError):
        _log_unexpected_error(session_id)


async def _persist_in_own_session(draft: _UsageEventDraft, usage_event: UsageEvent) -> None:
    """Write the event in a session of its own, retrying a locked SQLite database up to three times."""
    session_id = draft.session_id
    for attempt in range(3):
        try:
            async with async_session_factory() as usage_db:
                attribution = await draft.attribute(usage_db)
                retried_event = usage_event if attempt == 0 else draft.new_event()
                _apply_attribution(retried_event, attribution)
                usage_db.add(retried_event)
                await usage_db.commit()
            return
        except OperationalError as exc:
            if not _is_sqlite_lock_error(exc) or attempt == 2:
                if _is_sqlite_lock_error(exc):
                    record_db_concurrency_event("usage_event", "sqlite_lock_skipped")
                logger.warning(
                    "Skipping usage event persistence for session %s after database lock",
                    session_id,
                    exc_info=exc,
                )
                return
            record_db_concurrency_event("usage_event", "sqlite_lock_retry")
            await asyncio.sleep(0.2 * (attempt + 1))
        except IntegrityError:
            _log_foreign_key_race(session_id)
            return
        except (SQLAlchemyError, TypeError, ValueError):
            _log_unexpected_error(session_id)
            return


async def record_usage_event(
    *,
    db: AsyncSession,
    session_id: str,
    user_id: str,
    provider: str,
    model: str,
    usage: dict[str, Any] | None,
    request_id: str | None = None,
    agent_chain_id: str | None = None,
    flow_definition_id: str | None = None,
    driver: str | None = None,
    dispatch_owner: str | None = None,
) -> None:
    """Persist one usage event with its attributed cost.

    ``driver`` is the provider driver key that actually served the turn. Only
    the governed gateway driver may declare a cost source in ``usage``; callers
    that cannot name their driver get the ungoverned attribution.
    ``dispatch_owner`` is the registered owner of the governed call; an
    unregistered key raises before anything is written.
    """

    owner_key = registered_dispatch_owner(dispatch_owner).key if dispatch_owner else None
    usage_payload = usage or {}
    tokens_in = _usage_prompt_tokens(usage_payload)
    tokens_out = _safe_usage_int(usage_payload.get("completion_tokens"))
    if provider == "workflow" and tokens_in <= 0 and tokens_out <= 0:
        return
    # A Bedrock Converse turn is recorded in the gateway's convention: uncached
    # input in ``tokens_in``, cache reads and writes in their own columns.
    converse = converse_prompt_split(usage_payload)
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    if converse is not None:
        tokens_in = converse.uncached_input_tokens
        cache_read_tokens = converse.cache_read_tokens
        cache_creation_tokens = converse.cache_write_tokens
    draft = _UsageEventDraft(
        session_id=session_id, user_id=user_id, provider=provider, model=model, usage_payload=usage_payload,
        tokens_in=tokens_in, tokens_out=tokens_out,
        cache_read_tokens=cache_read_tokens, cache_creation_tokens=cache_creation_tokens,
        request_id=request_id, owner_key=owner_key, agent_chain_id=agent_chain_id,
        flow_definition_id=flow_definition_id, driver=driver,
    )
    usage_event = draft.new_event()
    if db is not None:
        await _persist_in_session(db, draft, usage_event)
        return
    await _persist_in_own_session(draft, usage_event)


# The main chat turn's model calls are dispatched by the engine runtime chain.
ENGINE_TURN_DISPATCH_OWNER = "engine_runtime_chain"


async def record_engine_turn_usage_event(
    *,
    db: AsyncSession,
    session_id: str,
    user_id: str,
    provider: str,
    model: str,
    usage: dict[str, Any] | None,
    request_id: str | None = None,
    agent_chain_id: str | None = None,
    flow_definition_id: str | None = None,
    driver: str | None = None,
) -> None:
    """The main turn's usage event, owned by the engine runtime chain."""
    await record_usage_event(
        db=db,
        session_id=session_id,
        user_id=user_id,
        provider=provider,
        model=model,
        usage=usage,
        request_id=request_id,
        agent_chain_id=agent_chain_id,
        flow_definition_id=flow_definition_id,
        driver=driver,
        dispatch_owner=ENGINE_TURN_DISPATCH_OWNER,
    )
