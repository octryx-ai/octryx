"""The reviewer's one governed model answer: no tools, no history, its own dispatch owner.

The runtimes are the Workspace's control-plane runtimes (as for workflow proposals), admitted for the run's
Workspace under the ``workflow_run_review`` dispatch owner; ``coding``-tagged runtimes are tried first, at most
two (the Reviewer agent's order: ``reviewer_agent.order_review_runtimes``). The reviewer is offered no tool, so
it can read only what the server put in front of it and can change nothing. No prompt, answer or provider
message is logged; usage is counted and recorded on the run.

Every review names its model and route (``review.choice``): on ``company`` only runtimes serving that
model are used (:func:`company_review_model`), on ``seat`` the review is a separate tool-less turn on the person's own
subscription (``review.seat``).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...content_security.handling import PLATFORM_RECORD_WITHOUT_WORKSPACE
from ...content_security.model_call_scope import ModelCallScope, call_scope, model_call_scope
from ...knowledge.research.model import first_json_object
from ...model_gateway.dispatch_admission import admit_runtimes_for_dispatch

logger = logging.getLogger(__name__)

DISPATCH_OWNER = "workflow_run_review"
MAX_RUNTIME_ATTEMPTS = 4
# The answer may use the model's whole output (its catalog limit): a capped answer is no verdict. With a
# fixed limit, answers on large reviews stopped at 8000 tokens. No
# artificial limits that cause problems. Used only when the runtime names no limit of its own.
MAX_ANSWER_TOKENS = 64000


class ReviewModelUnavailableError(Exception):
    """A fixed, bounded refusal: ``reason`` is a constant, never provider text."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"workflow run review model unavailable: {reason}")
        self.reason = reason


# Models whose price steps up for a whole call above a prompt size: ``{name part: (prompt tokens, factor)}``. The same
# list price the device launcher knows (``octryx_claude.device_turn_kind.PRICE_TIERS``): Haiku 5.5 is 0.10 $/M
# input up to 100K prompt tokens and 0.50 $/M beyond, output likewise ×5. Measured: 11 of 13 story
# reviews of a run were 111K-153K tokens in and their usage cost was linear (151K in → 0.0226 $).
PRICE_TIERS: dict[str, tuple[int, int]] = {"haiku-5-5": (100_000, 5)}


def price_tier(model: str) -> tuple[int, int] | None:
    """``(prompt tokens, factor)`` of the model's price step, ``None`` when its price is flat."""
    tiers = [tier for name, tier in PRICE_TIERS.items() if name in str(model or "").lower()]
    return min(tiers) if tiers else None


@dataclass(slots=True)
class ReviewUsage:
    model: str = ""
    provider: str = ""
    driver: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    # The part of tokens_in/out that came from calls above the model's price tier (``price_tier``), and its factor.
    over_tier_in: int = 0
    over_tier_out: int = 0
    tier_factor: int = 1
    # ``seat`` when the call ran on the person's own subscription (``review.seat``): it costs the platform nothing.
    route: str = ""


def call_usage(model: str, provider: str, driver: str, tokens_in: int, tokens_out: int, *,
               route: str = "") -> ReviewUsage:
    """One call's usage; a call above its model's price tier is marked so its cost is priced at the step."""
    tier = price_tier(model)
    over = tier is not None and tokens_in > tier[0]
    return ReviewUsage(model=model, provider=provider, driver=driver, tokens_in=tokens_in, tokens_out=tokens_out,
                       over_tier_in=tokens_in if over else 0, over_tier_out=tokens_out if over else 0,
                       tier_factor=tier[1] if over else 1, route=route)


def summed_usage(a: ReviewUsage, b: ReviewUsage) -> ReviewUsage:
    """Two calls of one review attempt as one usage (the later call's model names it)."""
    return ReviewUsage(model=b.model or a.model, provider=b.provider or a.provider, driver=b.driver or a.driver,
                       tokens_in=a.tokens_in + b.tokens_in, tokens_out=a.tokens_out + b.tokens_out,
                       over_tier_in=a.over_tier_in + b.over_tier_in, over_tier_out=a.over_tier_out + b.over_tier_out,
                       tier_factor=max(a.tier_factor, b.tier_factor),
                       route=_summed_route(a.route, b.route))


def _summed_route(a: str, b: str) -> str:
    """One attempt's route: the same for both calls, else ``mixed`` (a seat call, then the company fallback)."""
    return a if a == b or not b else b if not a else "mixed"


@dataclass(slots=True)
class ReviewAnswer:
    answer: dict[str, Any] | None
    usage: ReviewUsage = field(default_factory=ReviewUsage)


class ReviewModel:
    def __init__(self, runtimes: list[dict[str, Any]], *, scope: ModelCallScope, runtime_shared: bool = False,
                 route: str = "") -> None:
        self._runtimes = runtimes[:MAX_RUNTIME_ATTEMPTS]
        self._scope = scope
        #: The review runs on the author's model because no other runtime is admitted.
        self.runtime_shared = runtime_shared
        #: ``company``: only runtimes serving the chosen review model (``review.choice``).
        self.route = route

    async def answer(self, *, system: str, user: str, images: list[Any] | None = None) -> ReviewAnswer:
        """``images``: screenshots (``review.screens.Screen``) shown after the text, each named before it."""
        from ....agent.providers import get_provider

        messages = [{"role": "system", "content": system}, {"role": "user", "content": user_content(user, images)}]
        for runtime in self._runtimes:
            client = None
            model = str(runtime.get("model") or "")
            try:
                client = get_provider(**{key: value for key, value in runtime.items() if key != "use_case_tags"})
                with model_call_scope(self._scope):
                    result = await client.chat(messages=messages, model=model, temperature=0.0,
                                               max_tokens=answer_tokens(runtime))
            except Exception:  # noqa: BLE001 - the next governed runtime is tried; no provider text is kept
                logger.warning("workflow_run_review runtime_failed")
                continue
            finally:
                close = getattr(client, "close", None) if client is not None else None
                if close:
                    await close()
            usage = dict((result or {}).get("usage") or {}) if isinstance(result, dict) else {}
            content = str((result or {}).get("content") or "") if isinstance(result, dict) else ""
            return ReviewAnswer(answer_object(content), call_usage(
                model, str(runtime.get("provider_name") or ""), str(runtime.get("driver") or ""),
                int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
                int(usage.get("completion_tokens") or usage.get("output_tokens") or 0), route=self.route))
        raise ReviewModelUnavailableError("model_unavailable")


def answer_tokens(runtime: dict[str, Any]) -> int:
    """The model's own output limit when the runtime names one, else :data:`MAX_ANSWER_TOKENS`."""
    try:
        limit = int(runtime.get("max_tokens_per_request") or 0)
    except (TypeError, ValueError):
        limit = 0
    return limit if limit > 0 else MAX_ANSWER_TOKENS


def user_content(user: str, images: list[Any] | None) -> str | list[dict[str, Any]]:
    """The user message: the text alone, or the text followed by each screenshot with its name."""
    if not images:
        return user
    import base64

    # The text is the same for every batch of one review: marked for the provider's prompt cache (LiteLLM passes
    # it to Anthropic and Bedrock), so the second batch reads it at the cache price.
    parts: list[dict[str, Any]] = [{"type": "text", "text": user, "cache_control": {"type": "ephemeral"}}]
    for screen in images:
        parts.append({"type": "text", "text": f"Screenshot: {screen.name}"})
        encoded = base64.b64encode(screen.data).decode()
        parts.append({"type": "image_url", "image_url": {"url": f"data:{screen.media_type};base64,{encoded}"}})
    return parts


_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def answer_object(text: str) -> dict[str, Any] | None:
    """The reviewer's answer object: the first JSON object with a ``verdict`` (or, for the audit stage, an
    ``audit``) key, also when trailing commas slipped in; else the first JSON object at all.

    Example (Gemma, UI diffs): the answer quoted a finding or an example as JSON before the verdict, the first
    object was taken and the review counted as no verdict four times in a row."""
    for candidate in (text, _TRAILING_COMMA.sub(r"\1", text)):
        position = candidate.find("{")
        while position >= 0:
            try:
                value, _ = _ANSWER_DECODER.raw_decode(candidate, position)
            except json.JSONDecodeError:
                value = None
            if isinstance(value, dict) and ("verdict" in value or "audit" in value):
                return value
            position = candidate.find("{", position + 1)
    return first_json_object(text)


_ANSWER_DECODER = json.JSONDecoder()


async def _chosen_model_runtimes(db: AsyncSession, runtimes: list[dict[str, Any]], model: str
                                 ) -> list[dict[str, Any]]:
    """The review node's chosen model on a provider the Workspace already routes to (otherwise, when the only
    active runtime target was Gemma, so ``config.model`` Haiku never reached the reviewer). The provider must list
    the model as active in its catalog; the admission below still decides (clearance, Workspace)."""
    from sqlalchemy import select

    from ....models import LLMModel

    chosen: list[dict[str, Any]] = []
    for runtime in runtimes:
        provider_id = str(runtime.get("provider_id") or "")
        if not provider_id or any(item.get("provider_id") == provider_id for item in chosen):
            continue
        row = (await db.execute(select(LLMModel).where(
            LLMModel.provider_id == provider_id, LLMModel.model_id == model,
            LLMModel.is_active.is_(True)))).scalars().first()
        if row is None:
            continue
        chosen.append({**runtime, "model": model, "use_case_tags": [], "supports_vision": bool(row.supports_vision),
                       "supports_tools": bool(row.supports_tools), "pricing_input": row.pricing_input,
                       "pricing_output": row.pricing_output, "target_temperature": row.temperature,
                       "max_tokens_per_request": row.max_tokens_per_request})
    return chosen


REASON_MODEL_NOT_ADMITTED = "review_model_not_admitted"


async def governed_review_model(db: AsyncSession, *, project_id: str | None, reviewer: Any = None,
                                model: str = "", choice: Any = None, run: Any = None) -> Any:
    """The review's model, or a fixed refusal.

    ``choice`` (``review.choice.ReviewChoice``, every current review): exactly the chosen model, on the
    chosen route: ``company`` is a Workspace runtime serving that model (none: ``review_model_not_admitted``, never
    another model); ``seat`` is the run's person's own subscription as a separate device turn (``review.seat``), with
    the visible company fallback when the seat is unavailable.

    Without ``choice``: the admitted runtimes of the Workspace, ``model`` first when admitted.
    ``reviewer`` is the Reviewer agent's setup (``reviewer_agent.ReviewerSetup``) on a version whose phases name
    agents: its runtime preference applies and the author's model is avoided when another runtime is admitted."""
    if choice is not None:
        async def company() -> ReviewModel:
            return await company_review_model(db, project_id=project_id, reviewer=reviewer, model=choice.model)

        if choice.route == "seat" and run is not None:
            from .seat_fallback import seat_review_model

            return await seat_review_model(db, run, choice, company)
        return await company()
    from ...workflow_routing.proposal_model import _workspace_runtimes

    runtimes = await _workspace_runtimes(db, project_id)
    if not runtimes:
        raise ReviewModelUnavailableError("no_runtime_configured")
    if model and all(str(runtime.get("model") or "") != model for runtime in runtimes):
        runtimes = [*await _chosen_model_runtimes(db, runtimes, model), *runtimes]
    admission = await admit_runtimes_for_dispatch(db, runtimes, project_ids=project_id, owner=DISPATCH_OWNER)
    if not admission.allowed:
        raise ReviewModelUnavailableError(str(admission.reason or admission.state))
    admitted = list(admission.dispatchable_runtimes())
    if not admitted:
        raise ReviewModelUnavailableError("no_admitted_runtime")
    from .reviewer_agent import order_review_runtimes

    ordered, shared = order_review_runtimes(admitted, reviewer, model=model)
    return ReviewModel(ordered, scope=_review_scope(project_id), runtime_shared=shared)


def _review_scope(project_id: str | None) -> ModelCallScope:
    """The run's Workspace (the one its runtimes were admitted for), or a run stored without one."""
    return call_scope(project_id, without_workspace=PLATFORM_RECORD_WITHOUT_WORKSPACE)


def _serves(runtime: dict[str, Any], model: str) -> bool:
    """The runtime serves exactly ``model`` (its model id, or the alias the Workspace names it by)."""
    return model in {str(runtime.get(key) or "") for key in ("model", "alias", "model_alias")}


async def company_review_model(db: AsyncSession, *, project_id: str | None, reviewer: Any = None,
                               model: str) -> ReviewModel:
    """Only the Workspace's admitted runtimes that serve ``model``: the review never runs on another model (live
    locally the only admitted runtime was a 9B Qwen stub; every review timed out on it)."""
    from ...workflow_routing.proposal_model import _workspace_runtimes

    runtimes = await _workspace_runtimes(db, project_id)
    serving = [runtime for runtime in runtimes if _serves(runtime, model)]
    serving += [runtime for runtime in await _chosen_model_runtimes(db, runtimes, model) if runtime not in serving]
    if not serving:
        raise ReviewModelUnavailableError(REASON_MODEL_NOT_ADMITTED)
    admission = await admit_runtimes_for_dispatch(db, serving, project_ids=project_id, owner=DISPATCH_OWNER)
    if not admission.allowed:
        raise ReviewModelUnavailableError(str(admission.reason or admission.state))
    admitted = [runtime for runtime in admission.dispatchable_runtimes() if _serves(runtime, model)]
    if not admitted:
        raise ReviewModelUnavailableError(REASON_MODEL_NOT_ADMITTED)
    shared = bool(reviewer is not None and getattr(reviewer, "author_model", "") == model)
    return ReviewModel(admitted, scope=_review_scope(project_id), runtime_shared=shared, route="company")


__all__ = ["DISPATCH_OWNER", "PRICE_TIERS", "REASON_MODEL_NOT_ADMITTED", "ReviewAnswer", "ReviewModel",
           "ReviewModelUnavailableError", "ReviewUsage", "call_usage", "company_review_model", "governed_review_model",
           "price_tier", "summed_usage"]
