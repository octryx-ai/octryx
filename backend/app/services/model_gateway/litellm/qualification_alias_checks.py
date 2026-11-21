"""Per-alias qualification checks: capability parity, integral usage, cost contract and model group identity."""

from __future__ import annotations

from typing import Any

from app.services.model_gateway.cost_contract import (
    COST_SOURCE_CATALOG_PRICING,
    COST_SOURCE_GATEWAY_REPORTED,
    COST_SOURCE_GOVERNED_FREE,
)

from .alias_catalog import AliasEntry
from .capability_evidence import CAPABILITY_EVIDENCE_FIELDS, ProbeEvidence
from .client import GatewayChatResult
from .errors import LiteLLMGatewayError
from .numeric_contract import finite_number
from .qualification_codes import (
    CHECK_CAPABILITY_PARITY,
    CHECK_COST_CONTRACT,
    CHECK_MODEL_GROUP_IDENTITY,
    CHECK_USAGE_INTEGRAL,
    REASON_CONTEXT_LIMIT_ABOVE_PROBE_MAX_INPUT,
    REASON_COST_NOT_FINITE,
    REASON_COST_NOT_POSITIVE,
    REASON_COST_NOT_ZERO,
    REASON_COST_SOURCE_MISMATCH,
    REASON_DECLARED_CAPABILITY_NOT_PROVEN,
    REASON_DECLARED_CAPABILITY_REFUTED,
    REASON_MODEL_GROUP_ABSENT_FROM_CATALOG,
    REASON_MODEL_GROUP_NOT_VERIFIED,
    REASON_PROMPT_TOKENS_NOT_POSITIVE,
    REASON_TOKENS_NOT_INTEGRAL,
)
from .qualification_report import QualificationCheck, _failed, _passed


def _capability_parity_check(entry: AliasEntry, evidence: ProbeEvidence) -> QualificationCheck:
    group = evidence.for_model_group(entry.model_group)
    if group is None:
        return _failed(
            CHECK_CAPABILITY_PARITY,
            alias=entry.alias,
            reason=REASON_MODEL_GROUP_ABSENT_FROM_CATALOG,
        )
    declared = entry.requested_capabilities
    refuted = sorted(declared & group.refuted_capabilities)
    unproven = sorted(declared - group.proven_capabilities - group.refuted_capabilities)
    detail: dict[str, Any] = {
        "declared_capabilities": sorted(declared),
        "proven_capabilities": sorted(group.proven_capabilities),
        "model_info_fields": sorted(CAPABILITY_EVIDENCE_FIELDS[name] for name in declared),
        "probe_max_input_tokens": group.max_input_tokens or 0,
        "context_limit": entry.context_limit,
    }
    if refuted:
        return _failed(
            CHECK_CAPABILITY_PARITY,
            alias=entry.alias,
            reason=REASON_DECLARED_CAPABILITY_REFUTED,
            refuted_capabilities=refuted,
            **detail,
        )
    if unproven:
        return _failed(
            CHECK_CAPABILITY_PARITY,
            alias=entry.alias,
            reason=REASON_DECLARED_CAPABILITY_NOT_PROVEN,
            unproven_capabilities=unproven,
            **detail,
        )
    if group.max_input_tokens is not None and entry.context_limit > group.max_input_tokens:
        # A context limit above what the model group accepts would push turns into
        # avoidable context-pressure failures.
        return _failed(
            CHECK_CAPABILITY_PARITY,
            alias=entry.alias,
            reason=REASON_CONTEXT_LIMIT_ABOVE_PROBE_MAX_INPUT,
            **detail,
        )
    return _passed(CHECK_CAPABILITY_PARITY, alias=entry.alias, **detail)


def _usage_checks(entry: AliasEntry, result: GatewayChatResult) -> list[QualificationCheck]:
    usage = result.usage
    return [
        _token_check(entry, usage.get("prompt_tokens"), usage.get("completion_tokens")),
        _cost_check(entry, usage.get("cost"), str(usage.get("cost_source") or "")),
        _model_group_check(entry, result),
    ]


def _token_check(entry: AliasEntry, prompt_tokens: Any, completion_tokens: Any) -> QualificationCheck:
    integral = (
        isinstance(prompt_tokens, int)
        and not isinstance(prompt_tokens, bool)
        and isinstance(completion_tokens, int)
        and not isinstance(completion_tokens, bool)
    )
    if not integral:
        return _usage_failure(entry, REASON_TOKENS_NOT_INTEGRAL)
    if prompt_tokens <= 0:
        return _usage_failure(entry, REASON_PROMPT_TOKENS_NOT_POSITIVE)
    return _passed(
        CHECK_USAGE_INTEGRAL,
        alias=entry.alias,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def _cost_check(entry: AliasEntry, cost: Any, source: str) -> QualificationCheck:
    # Finite, not merely numeric: ``NaN`` is false for every comparison below, so
    # it would pass "strictly positive" and "exactly zero" alike.
    cost_value = finite_number(cost)
    if source != entry.cost.source:
        return _failed(
            CHECK_COST_CONTRACT,
            alias=entry.alias,
            reason=REASON_COST_SOURCE_MISMATCH,
            declared_cost_source=entry.cost.source,
        )
    if cost_value is None:
        # Missing, malformed, NaN or infinite. None of them can be compared to a
        # budget threshold, so none of them settles a cost contract.
        return _failed(CHECK_COST_CONTRACT, alias=entry.alias, reason=REASON_COST_NOT_FINITE, cost_source=source)
    if source == COST_SOURCE_GOVERNED_FREE and cost_value != 0.0:
        return _failed(CHECK_COST_CONTRACT, alias=entry.alias, reason=REASON_COST_NOT_ZERO, cost_source=source)
    if source in (COST_SOURCE_GATEWAY_REPORTED, COST_SOURCE_CATALOG_PRICING) and cost_value <= 0.0:
        return _failed(CHECK_COST_CONTRACT, alias=entry.alias, reason=REASON_COST_NOT_POSITIVE, cost_source=source)
    return _passed(
        CHECK_COST_CONTRACT,
        alias=entry.alias,
        cost_source=source,
        cost_is_positive=cost_value > 0.0,
        cost_is_zero=cost_value == 0.0,
    )


def _model_group_check(entry: AliasEntry, result: GatewayChatResult) -> QualificationCheck:
    verified = bool(result.evidence.get("model_group_verified")) and result.model_group == entry.model_group
    if verified:
        return _passed(CHECK_MODEL_GROUP_IDENTITY, alias=entry.alias, model_group_verified=True)
    return _failed(CHECK_MODEL_GROUP_IDENTITY, alias=entry.alias, reason=REASON_MODEL_GROUP_NOT_VERIFIED)


def _usage_failure(entry: AliasEntry, reason: str) -> QualificationCheck:
    return _failed(CHECK_USAGE_INTEGRAL, alias=entry.alias, reason=reason)


def _alias_dispatch_failure(entry: AliasEntry, error: LiteLLMGatewayError) -> list[QualificationCheck]:
    detail = {"gateway_state": error.gateway_state, "denial_reason": error.denial_reason}
    return [
        _failed(CHECK_USAGE_INTEGRAL, alias=entry.alias, **detail),
        _failed(CHECK_COST_CONTRACT, alias=entry.alias, **detail),
        _failed(CHECK_MODEL_GROUP_IDENTITY, alias=entry.alias, **detail),
    ]
