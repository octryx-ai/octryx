"""The governed model path of a governed agent run: Model Policy -> admitted gateway runtimes."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runtime.engine_limits import APPROX_CHARS_PER_TOKEN
from app.agent.runtime.execution_support import record_usage_event
from app.agent.runtime.retry_policy import build_runtime_retry_policy
from app.agent.runtime.runtime_admission_contract import admission_refusal_of_attempts
from app.agent.runtime.runtime_errors import RUNTIME_ERROR_DATA_POLICY_DENIED
from app.agent.runtime.runtime_fallback import _chat_with_runtime_fallback

from ...exceptions.tool import BudgetLimitExceededError
from ...models import ModelPolicy, ModelPolicyRevision
from ...models.runtime.governed_revision import REGISTRY_STATUS_RETIRED, REVISION_STATE_PUBLISHED
from ..budget import compute_usage_event_cost_attribution, enforce_budget_limits
from ..content_security.model_call_scope import model_call_scope, workspace_call
from ..content_security.refusal import TURN_ERROR_CONTENT_BLOCKED, turn_error_class
from ..control_plane_service import resolve_control_plane_runtimes
from ..model_gateway.dispatch_admission import (
    DISPATCH_STATE_DENIED,
    REASON_CONTEXT_NOT_AUTHORIZED,
    REASON_CONTEXT_UNRESOLVABLE,
    admit_runtimes_for_dispatch,
)
from ..model_gateway.litellm.runtime_admission import runtime_uses_gateway_driver
from ..model_policy.entries import entries_digest
from ..model_policy.references import ResourceRef
from ..model_selection.platform_order import FALLBACK_STOP, load_fallback_choice
from .context import ExecutionContext
from .model_failover import AliasChain, ModelFailover, alias_chains, dispatch_with_failover, log_failover
from .provider_failure import failure_detail
from .refusals import RunRefusal, denied, failed, needs_configuration

logger = logging.getLogger(__name__)
DEFAULT_MAX_TOKENS = 4096
DEFAULT_REQUEST_TIMEOUT_SECONDS = 150.0

# The Workspace itself could not be admitted: a prohibition, not a grant gap.
_WORKSPACE_REFUSALS = frozenset({REASON_CONTEXT_UNRESOLVABLE, REASON_CONTEXT_NOT_AUTHORIZED})

RuntimeResolver = Callable[..., Awaitable[list[dict[str, Any]]]]


async def load_policy_aliases(db: AsyncSession, workspace_id: str, ref: ResourceRef) -> list[str]:
    policy = (
        await db.execute(
            select(ModelPolicy).where(ModelPolicy.workspace_id == workspace_id, ModelPolicy.name == ref.name)
        )
    ).scalar_one_or_none()
    if policy is None or policy.status == REGISTRY_STATUS_RETIRED or ref.revision is None:
        raise needs_configuration("model_policy_unresolved")
    revision = (
        await db.execute(
            select(ModelPolicyRevision).where(
                ModelPolicyRevision.policy_id == policy.id,
                ModelPolicyRevision.revision == ref.revision,
                ModelPolicyRevision.state == REVISION_STATE_PUBLISHED,
            )
        )
    ).scalar_one_or_none()
    entries = revision.entries_json if revision is not None else None
    if not isinstance(entries, list) or entries_digest(entries) != revision.digest:
        raise needs_configuration("model_policy_unresolved")
    aliases = [str(entry.get("alias") or "") for entry in entries if isinstance(entry, dict)]
    if not aliases or not all(aliases):
        raise needs_configuration("model_policy_unresolved")
    return aliases


async def admitted_runtimes(
    db: AsyncSession,
    *,
    workspace_id: str,
    aliases: list[str],
    requires_tools: bool,
    resolve_runtimes: RuntimeResolver = resolve_control_plane_runtimes,
    owner: str,
) -> list[dict[str, Any]]:
    resolved = await resolve_runtimes(db, requires_tools=requires_tools)
    gateway = [runtime for runtime in resolved if runtime_uses_gateway_driver(runtime)]
    ordered = [runtime for alias in aliases for runtime in gateway if str(runtime.get("model") or "").strip() == alias]
    if not ordered:
        raise needs_configuration("model_runtime_unavailable")
    admission = await admit_runtimes_for_dispatch(db, ordered, project_ids=[workspace_id], owner=owner)
    dispatchable = list(admission.dispatchable_runtimes()) if admission.allowed else []
    if dispatchable:
        return dispatchable
    if admission.state == DISPATCH_STATE_DENIED and admission.reason in _WORKSPACE_REFUSALS:
        raise denied("model_alias_not_admitted")
    # An alias the project does not grant is a grant gap an administrator closes.
    raise needs_configuration("model_alias_not_admitted")


class GovernedModelCall:
    def __init__(
        self,
        db: AsyncSession,
        context: ExecutionContext,
        runtimes: list[dict[str, Any]],
        *,
        get_provider: Callable[..., Any] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        dispatch_owner: str,
    ) -> None:
        self._db = db
        self._dispatch_owner = dispatch_owner
        self._context = context
        self._get_provider = get_provider
        self._max_tokens = max_tokens
        self._chains = alias_chains(runtimes)
        # Sticky across the run's requests: after a switch, later requests start here.
        self._chain_index = 0
        # The platform fallback mode, read on the first call: "stop" never switches aliases.
        self._fallback_stop: bool | None = None
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost_usd = Decimal("0")
        #: Closed switch facts ``{from_alias, to_alias, error_class, error_class_source}``.
        self.failovers: list[dict[str, str]] = []

    async def _enforce_budget(self, messages: list[dict[str, Any]], chain: AliasChain) -> None:
        context = self._context
        try:
            await enforce_budget_limits(
                self._db,
                session_id=context.session_id,
                user_id=context.user_id,
                project_id=context.workspace_id,
                runtimes=list(chain.runtimes),
                messages=messages,
                max_completion_tokens=self._max_tokens,
                approx_chars_per_token=APPROX_CHARS_PER_TOKEN,
            )
        except BudgetLimitExceededError as exc:
            raise failed("budget_limit_exceeded") from exc

    def _record_switch(self, switch: ModelFailover) -> None:
        self.failovers.append(switch.as_fact())
        self._chain_index += 1
        log_failover(attempt_id=self._context.attempt_id, dispatch_owner=self._dispatch_owner, switch=switch)

    async def __call__(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        if not self._chains:
            raise needs_configuration("model_runtime_unavailable")
        # The content policies run at the provider boundary (content_security.model_call) for every request.
        dispatch_messages = messages
        await self._enforce_budget(dispatch_messages, self._chains[self._chain_index])

        async def dispatch(chain: AliasChain) -> tuple[dict[str, Any], dict[str, Any]]:
            runtimes = list(chain.runtimes)
            with model_call_scope(workspace_call(self._context.workspace_id, session_id=self._context.session_id,
                                                 user_id=self._context.user_id)):
                response, runtime, _attempts = await _chat_with_runtime_fallback(
                    runtimes,
                    messages=dispatch_messages,
                    tools=tools,
                    max_tokens=self._max_tokens,
                    request_timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS,
                    get_provider_func=self._provider_factory(),
                    retry_policy=build_runtime_retry_policy(
                        {"runtime_fallback_mode": "first_runtime_only" if self._fallback_stop else "all_runtimes"},
                        runtimes=runtimes,
                    ),
                )
            return response, runtime

        async def before_switch(chain: AliasChain) -> None:
            await self._enforce_budget(dispatch_messages, chain)

        if self._fallback_stop is None:
            self._fallback_stop = await load_fallback_choice(self._db) == FALLBACK_STOP
        chains = self._chains[: self._chain_index + 1] if self._fallback_stop else self._chains
        try:
            response, runtime = await dispatch_with_failover(
                chains,
                start=self._chain_index,
                dispatch=dispatch,
                before_switch=before_switch,
                on_switch=self._record_switch,
            )
        except RunRefusal:
            raise
        except Exception as exc:  # noqa: BLE001 - the chain's own failure type; classified from typed facts only
            if turn_error_class(exc) == TURN_ERROR_CONTENT_BLOCKED:
                raise failed(TURN_ERROR_CONTENT_BLOCKED) from None
            refusal = admission_refusal_of_attempts(getattr(exc, "runtime_attempts", None))
            if refusal == RUNTIME_ERROR_DATA_POLICY_DENIED:
                raise denied("model_data_policy_denied") from None
            if refusal is not None:
                raise needs_configuration("model_alias_not_admitted") from None
            detail = failure_detail(getattr(exc, "runtime_attempts", None))
            logger.warning("governed_model_provider_error owner=%s attempt=%s cause=%s",
                           self._dispatch_owner, self._context.attempt_id, detail or "unknown")
            raise failed("provider_error", detail=detail) from None
        await self._account(dict(response or {}), dict(runtime or {}))
        return response

    def _provider_factory(self) -> Callable[..., Any]:
        if self._get_provider is not None:
            return self._get_provider
        from ...agent import providers

        return providers.get_provider

    async def _account(self, response: dict[str, Any], runtime: dict[str, Any]) -> None:
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        tokens_in = max(0, int(usage.get("prompt_tokens") or 0))
        tokens_out = max(0, int(usage.get("completion_tokens") or 0))
        provider = str(runtime.get("provider_name") or "")
        model = str(response.get("model") or runtime.get("model") or "")
        driver = str(runtime.get("driver") or "") or None
        attribution = await compute_usage_event_cost_attribution(
            self._db,
            provider=provider,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            usage=usage,
            driver=driver,
        )
        await record_usage_event(
            db=self._db,
            session_id=self._context.session_id,
            user_id=self._context.user_id,
            provider=provider,
            model=model,
            usage=usage,
            driver=driver,
            dispatch_owner=self._dispatch_owner,
        )
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        cost = attribution.cost if isinstance(attribution.cost, Decimal) else Decimal(str(attribution.cost or 0))
        if cost.is_finite() and cost > 0:
            self.cost_usd += cost


__all__ = ["GovernedModelCall", "RuntimeResolver", "admitted_runtimes", "load_policy_aliases"]
