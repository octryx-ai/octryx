"""The process-wide policy-engine snapshot: the instance mode and the published custom policies.

The enforcement points that consult Cedar are partly synchronous (``ProjectModelAdmission.decide``,
``classification_tool_decision``), so they read this snapshot instead of the database. The async enforcement
points call :func:`maintain_policy_runtime`, which reloads the snapshot when it is older than
:data:`REFRESH_SECONDS` and flushes the buffered decision-log records. Both use their own database session, so a
policy-engine failure can never touch the caller's transaction.

Mode (``system_config`` key :data:`MODE_CONFIG_KEY`): ``off`` | ``shadow`` | ``enforce``; no row is ``shadow``,
and so is an unreadable value (shadow never changes a decision). Until the first load the snapshot is the
default: shadow, no custom policies.

A published custom set that no longer parses (a schema change after publishing) is ``custom_invalid``. It does
not deny everything: the enforcement points evaluate the baseline alone, so the custom policies fall back to
shadow (they are not applied) in every mode. The change to an invalid set is an alert: logged as an error and
audited (:data:`AUDIT_CUSTOM_SET_INVALID`, actor: the admin who published the set) once per process and set; the
status view shows it and counts the fallback decisions per point (``shadow.custom_fallback_counters``); enforce
readiness refuses (``custom_set_invalid``) until a valid version is published.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.content_detection.custom_definitions import EMPTY_DEFINITIONS, DetectorDefinitions, DetectorSetError
from app.services.content_detection.custom_validation import check_detector_set

from ...models import AuditLog, LLMProvider, PolicySetVersion, SystemConfig
from ...models.runtime.governed_revision import (
    REVISION_STATE_DRAFT,
    REVISION_STATE_IN_REVIEW,
    REVISION_STATE_PUBLISHED,
)
from .engine import PolicySetInvalidError, compile_policy_set

logger = logging.getLogger(__name__)

MODE_CONFIG_KEY = "policy_engine.mode"
MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ENFORCE = "enforce"
MODES: tuple[str, ...] = (MODE_OFF, MODE_SHADOW, MODE_ENFORCE)
DEFAULT_MODE = MODE_SHADOW
REFRESH_SECONDS = 15.0
AUDIT_CUSTOM_SET_INVALID = "policy_engine.custom_set_invalid_fallback"


@dataclass(frozen=True, slots=True)
class PolicyRuntime:
    mode: str = DEFAULT_MODE
    custom_text: str = ""
    custom_ids: frozenset[str] = frozenset()
    custom_version: int | None = None
    custom_digest: str | None = None
    custom_invalid: bool = False
    loaded_at: float | None = None
    # The open draft (or the version in review) for the draft shadow; empty without one.
    draft_text: str = ""
    draft_ids: frozenset[str] = frozenset()
    draft_version: int | None = None
    draft_digest: str | None = None
    # The custom content detectors of the published version and of the draft.
    custom_detectors: DetectorDefinitions = EMPTY_DEFINITIONS
    draft_detectors: DetectorDefinitions = EMPTY_DEFINITIONS
    # ``ModelAlias.approved_for``: alias → the categories its catalog entry is approved for. An alias that
    # several gateway providers list gets the categories all of them approve.
    alias_approvals: Mapping[str, frozenset[str]] = field(default_factory=dict)

    @property
    def key(self) -> tuple:
        approvals = tuple(sorted((alias, tuple(sorted(items))) for alias, items in self.alias_approvals.items()))
        return (self.mode, self.custom_digest, self.custom_invalid, self.draft_digest, approvals)


_current = PolicyRuntime()


def current_runtime() -> PolicyRuntime:
    return _current


def set_policy_runtime(runtime: PolicyRuntime) -> None:
    global _current
    _current = runtime


def reset_policy_runtime() -> None:
    set_policy_runtime(PolicyRuntime())


def parse_mode(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if text in MODES else DEFAULT_MODE


async def load_mode(db: AsyncSession) -> str:
    row = await db.get(SystemConfig, MODE_CONFIG_KEY)
    return parse_mode(row.value) if row is not None and row.value else DEFAULT_MODE


async def published_version(db: AsyncSession) -> PolicySetVersion | None:
    stmt = select(PolicySetVersion).where(PolicySetVersion.state == REVISION_STATE_PUBLISHED)
    return (await db.execute(stmt.order_by(PolicySetVersion.version.desc()).limit(1))).scalar_one_or_none()


async def _draft_fields(db: AsyncSession, published_digest: str | None) -> dict:
    """The newest draft or version in review that parses and differs from the published set, else nothing."""
    stmt = (select(PolicySetVersion)
            .where(PolicySetVersion.state.in_([REVISION_STATE_DRAFT, REVISION_STATE_IN_REVIEW]))
            .order_by(PolicySetVersion.version.desc()).limit(1))
    draft = (await db.execute(stmt)).scalar_one_or_none()
    if draft is None or draft.digest == published_digest:
        return {}
    text = str(draft.policies_text or "")
    try:
        compile_policy_set(text)
        detectors = check_detector_set(draft.content_detectors)
    except (PolicySetInvalidError, DetectorSetError):
        return {}
    return {"draft_text": text, "draft_ids": frozenset(str(item) for item in draft.policy_ids or ()),
            "draft_version": int(draft.version), "draft_digest": str(draft.digest), "draft_detectors": detectors}


async def alias_approvals(db: AsyncSession) -> dict[str, frozenset[str]]:
    """The approved content categories per gateway alias, from the active LiteLLM gateway providers."""
    from ..model_gateway.litellm.alias_catalog import admitted_alias_entries
    from ..model_gateway.litellm.runtime_admission import LITELLM_GATEWAY_DRIVER

    stmt = select(LLMProvider.config_json).where(LLMProvider.is_active.is_(True),
                                                 LLMProvider.driver == LITELLM_GATEWAY_DRIVER)
    approvals: dict[str, frozenset[str]] = {}
    for config in (await db.execute(stmt)).scalars():
        for entry in admitted_alias_entries(config):
            current = approvals.get(entry.alias)
            approved = entry.approved_data_categories
            approvals[entry.alias] = approved if current is None else current & approved
    return approvals


async def load_policy_runtime(db: AsyncSession) -> PolicyRuntime:
    from ..data_classification.levels import refresh_level_registry

    await refresh_level_registry(db)  # the classification levels the generated policies and ranks use
    from ..tool_approval_policy import refresh_platform_default

    await refresh_platform_default(db)  # the tool-approval platform default the synchronous gate reads
    from app.services.knowledge.projection.workspace_classification_values import instance_default_for

    await instance_default_for(db)  # the Instance default the synchronous MCP decision falls back to
    mode = await load_mode(db)
    version = await published_version(db)
    approvals = await alias_approvals(db)
    if version is None:
        return PolicyRuntime(mode=mode, loaded_at=time.monotonic(), alias_approvals=approvals,
                             **await _draft_fields(db, None))
    text = str(version.policies_text or "")
    invalid = False
    detectors = EMPTY_DEFINITIONS
    try:
        compile_policy_set(text)
        detectors = check_detector_set(version.content_detectors)
    except (PolicySetInvalidError, DetectorSetError):
        invalid = True
    return PolicyRuntime(
        mode=mode,
        custom_text=text,
        custom_ids=frozenset(str(item) for item in version.policy_ids or ()),
        custom_version=int(version.version),
        custom_digest=str(version.digest),
        custom_invalid=invalid,
        custom_detectors=detectors,
        alias_approvals=approvals,
        loaded_at=time.monotonic(),
        **await _draft_fields(db, str(version.digest)),
    )


async def refresh_policy_runtime(db: AsyncSession) -> PolicyRuntime:
    previous = _current
    runtime = await load_policy_runtime(db)
    set_policy_runtime(runtime)
    if runtime.custom_invalid and (not previous.custom_invalid or previous.custom_digest != runtime.custom_digest):
        await _alert_custom_set_invalid(runtime)
    return runtime


async def _alert_custom_set_invalid(runtime: PolicyRuntime) -> None:
    """Log and audit (own session) that the published set no longer parses and is not applied. Never raises."""
    from ...db import core as db_core

    logger.error("policy_engine_custom_set_invalid version=%s mode=%s: custom policies fall back to shadow",
                 runtime.custom_version, runtime.mode)
    try:
        async with db_core.async_session_factory() as session:
            version = await published_version(session)
            if version is None or not version.published_by:
                return
            session.add(AuditLog(user_id=version.published_by, action=AUDIT_CUSTOM_SET_INVALID,
                                 resource_type="policy_set_version", resource_id=version.id,
                                 details={"version": version.version, "digest": version.digest, "mode": runtime.mode,
                                          "fallback": MODE_SHADOW}))
            await session.commit()
    except Exception:  # noqa: BLE001 - the alert must never break a live decision
        logger.warning("policy_engine_custom_set_invalid_audit_failed", exc_info=True)


def _stale(runtime: PolicyRuntime) -> bool:
    return runtime.loaded_at is None or time.monotonic() - runtime.loaded_at >= REFRESH_SECONDS


# One maintenance at a time per process. Each run opens its own sessions while the caller still holds its request's
# connection; when every parallel request ran it (stale snapshot, 15 s), 15 requests held the whole pool and each
# waited for a second connection: deadlock, every request 500. With
# one run at a time at most one extra connection is needed, and the other callers do not wait for it: they decide
# on the current snapshot, finish and free their connections.
_maintaining = False


async def maintain_policy_runtime(*, force: bool = False) -> None:
    """Reload a stale snapshot and flush buffered decision records, each in its own session. Never raises.

    Returns at once, on the current snapshot, while another maintenance runs in this process, ``force`` too (an
    admin change reloads through :func:`refresh_policy_runtime` on its own session, not through here)."""
    global _maintaining
    if _maintaining:
        return
    _maintaining = True
    try:
        await _maintain(force=force)
    finally:
        _maintaining = False


async def _maintain(*, force: bool) -> None:
    from ...db import core as db_core
    from .decision_log import flush_decision_log, pending_records

    if force or _stale(_current):
        try:
            async with db_core.async_session_factory() as session:
                await refresh_policy_runtime(session)
        except Exception:  # noqa: BLE001 - the policy engine must never break a live decision
            # Keep the last snapshot and retry after the interval, not on every decision.
            set_policy_runtime(replace(_current, loaded_at=time.monotonic()))
            logger.warning("policy_engine_runtime_refresh_failed", exc_info=True)
    if pending_records():
        try:
            await flush_decision_log()
        except Exception:  # noqa: BLE001 - see above
            logger.warning("policy_engine_decision_log_flush_failed", exc_info=True)
    await _flush_draft_impact(db_core)


async def _flush_draft_impact(db_core) -> None:
    """Write the draft-shadow buckets and, on the hourly schedule, prune them by the decision-log retention."""
    from .decision_log import retention_days
    from .draft_shadow import draft_prune_due, flush_draft_impact, pending_buckets

    prune = draft_prune_due()
    if not pending_buckets() and not prune:
        return
    try:
        async with db_core.async_session_factory() as session:
            await flush_draft_impact(session, prune_days=await retention_days(session) if prune else None)
            await session.commit()
    except Exception:  # noqa: BLE001 - the draft shadow is informational: dropped, never raised
        logger.warning("policy_engine_draft_impact_flush_failed", exc_info=True)


__all__ = [
    "AUDIT_CUSTOM_SET_INVALID",
    "DEFAULT_MODE",
    "MODES",
    "MODE_CONFIG_KEY",
    "MODE_ENFORCE",
    "MODE_OFF",
    "MODE_SHADOW",
    "PolicyRuntime",
    "alias_approvals",
    "current_runtime",
    "load_mode",
    "load_policy_runtime",
    "maintain_policy_runtime",
    "parse_mode",
    "published_version",
    "refresh_policy_runtime",
    "reset_policy_runtime",
    "set_policy_runtime",
]
