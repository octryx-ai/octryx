"""A run's hard limits at the model gateway: no model above the run's, no work past its cost budget."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import UsageEvent, WorkflowRun, WorkflowRunSession

EVENT_MODEL_MAPPED = "model_guard_mapped"
EVENT_SEAT_EQUIVALENT = "budget_seat_equivalent"
REASON_RUN_BUDGET = "workflow_run_budget_exhausted"
BUDGET_KEY = "cost_usd"
USAGE_KEY = "list_cost_usd"
DEFAULT_RUN_BUDGET_USD = 4.0
BUDGET_CEILING_FACTOR = 3
SPEND_CACHE_SECONDS = 10.0
_TIERS = (("haiku", 1), ("sonnet", 2), ("opus", 3))
# Codex's models on the person's ChatGPT seat, ranked on their own and never mixed with Claude's.
_CODEX_TIERS = (("luna", 1), ("terra", 2), ("sol", 3), ("astra", 4))
ENGINE_CODEX = "codex"
# USD per million tokens (input, output), list price; cache read 0.1x and cache write 1.25x the input price.
# Haiku 5.5 above a 100K-token prompt is charged at the long-context tier.
_PRICES = {"haiku": (0.10, 0.50), "sonnet": (2.00, 10.00), "opus": (4.00, 20.00),
           # OpenAI list prices from public aggregators (no official page found): luna and sol; terra
           # and astra are not published there and count conservatively as sol and twice sol.
           "luna": (0.10, 0.50), "terra": (2.00, 10.00), "sol": (2.00, 10.00), "astra": (4.00, 20.00)}
_HAIKU_LONG = (0.50, 2.50)
_LONG_PROMPT = 100_000
_spend_cache: dict[str, tuple[float, float]] = {}


def _is_codex(model: str) -> bool:
    return str(model or "").lower().startswith("gpt-")


def model_tier(model: str) -> int | None:
    name = str(model or "").lower()
    if _is_codex(name):
        return None
    return next((rank for word, rank in _TIERS if word in name), None)


def codex_tier(model: str) -> int | None:
    name = str(model or "").lower()
    if not _is_codex(name):
        return None
    return next((rank for word, rank in _CODEX_TIERS if word in name), None)


def _family(model: str) -> str | None:
    name = str(model or "").lower()
    tiers = _CODEX_TIERS if _is_codex(name) else _TIERS
    return next((word for word, _ in tiers if word in name), None)


def list_cost(model: str, *, tokens_in: int, tokens_out: int, cache_read: int = 0, cache_write: int = 0) -> float:
    from ...budget.api_equivalent import api_equivalent_usd

    listed = api_equivalent_usd(model, {"input_tokens": tokens_in, "output_tokens": tokens_out,
                                        "cache_read_input_tokens": cache_read,
                                        "cache_creation_input_tokens": cache_write})
    if listed is not None:
        return float(listed)
    family = _family(model)
    if family is None:
        return 0.0
    prompt = tokens_in + cache_read + cache_write
    price_in, price_out = _HAIKU_LONG if family == "haiku" and prompt > _LONG_PROMPT else _PRICES[family]
    return (tokens_in * price_in + cache_read * price_in * 0.1 + cache_write * price_in * 1.25
            + tokens_out * price_out) / 1_000_000


def _models_in(value: Any) -> list[str]:
    if isinstance(value, dict):
        found = [str(value["model"]).strip()] if isinstance(value.get("model"), str) and value["model"].strip() else []
        return found + [model for item in value.values() if isinstance(item, dict | list) for model in _models_in(item)]
    if isinstance(value, list):
        return [model for item in value for model in _models_in(item)]
    return []


@dataclass(frozen=True)
class RunModels:
    allowed: frozenset[str]
    ceiling: str
    phase: str

    def replacement(self, requested: str, *, engine: str = "") -> str | None:
        requested = str(requested or "").strip()
        if engine == ENGINE_CODEX:
            codex = [model for model in self.allowed if codex_tier(model) is not None]
            tier = codex_tier(requested)
            if not codex or tier is None:
                return None
            ceiling = max(codex, key=lambda model: codex_tier(model) or 0)
            return ceiling if tier > (codex_tier(ceiling) or 0) else None
        if not self.ceiling or not requested or requested in self.allowed:
            return None
        tier, ceiling = model_tier(requested), model_tier(self.ceiling)
        if tier is not None and ceiling is not None and tier <= ceiling:
            return None
        return self.phase or self.ceiling


def run_models(nodes: dict[str, Any], current_node_id: str | None, target_model: str = "") -> RunModels:
    named = [model for node in nodes.values() for model in _models_in(dict(getattr(node, "config", None) or {}))]
    if target_model:
        named.append(target_model)
    if not named:
        return RunModels(frozenset(), "", "")
    known = [model for model in named if model_tier(model) is not None]
    claude_named = [model for model in named if not _is_codex(model)]
    if not known and not claude_named:  # only Codex models: the Claude ceiling stays empty
        return RunModels(frozenset(named), "", "")
    ceiling = max(known, key=lambda model: model_tier(model) or 0) if known else claude_named[0]
    current = dict(getattr(nodes.get(str(current_node_id or "")), "config", None) or {})
    # The current phase's own model: its explicit ``model``, the model its turn runs on (``turn_phase_model``).
    phase = str(current.get("model") or "").strip()
    return RunModels(frozenset(named), ceiling, "" if _is_codex(phase) else phase)


async def _models_for(db: AsyncSession, run: WorkflowRun) -> RunModels:
    from ..graph import graph_for_run
    from ..runtime_target.target import stored_target

    graph = await graph_for_run(db, run)
    target = stored_target(run) or {}
    target_model = str(target.get("model") or "").strip()
    return run_models(await _with_class_models(db, run, dict(graph.nodes), target_model), run.current_node_id,
                      target_model)


async def _with_class_models(db: AsyncSession, run: WorkflowRun, nodes: dict[str, Any],
                             target_model: str) -> dict[str, Any]:
    from types import SimpleNamespace

    from ..graph import NODE_PHASE
    from .seat_models import choose, levels_for

    levels = await levels_for(db, run)

    def resolved(config: dict[str, Any]) -> dict[str, Any]:
        capability = str(dict(config.get("workflow_contract") or {}).get("capability_class") or "")
        model = choose(levels, config, capability_class=capability, run_model=target_model).model
        return {**config, "model": model} if model else config

    out: dict[str, Any] = {}
    for node_id, node in nodes.items():
        config = dict(getattr(node, "config", None) or {})
        if getattr(node, "kind", NODE_PHASE) == NODE_PHASE:
            config = resolved(config)
        roles = config.get("roles")
        if isinstance(roles, dict):
            config["roles"] = {key: resolved(dict(role)) if isinstance(role, dict) else role
                               for key, role in roles.items()}
        out[node_id] = SimpleNamespace(kind=getattr(node, "kind", ""), config=config)
    return out


async def run_spend(db: AsyncSession, run: WorkflowRun) -> float:
    return (await run_costs(db, run))[0]


async def run_costs(db: AsyncSession, run: WorkflowRun) -> tuple[float, float]:
    cached = _spend_cache.get(run.id)
    if cached is not None and time.monotonic() - cached[0] < SPEND_CACHE_SECONDS:
        return cached[1]
    sessions = select(WorkflowRunSession.session_id).where(WorkflowRunSession.run_id == run.id)
    rows = (await db.execute(
        select(UsageEvent.model, UsageEvent.tokens_in, UsageEvent.tokens_out, UsageEvent.cache_read_tokens,
               UsageEvent.cache_creation_tokens, UsageEvent.cost, UsageEvent.provider, UsageEvent.cost_source)
        .where(UsageEvent.session_id.in_(sessions), UsageEvent.created_at >= run.created_at)
    )).all()
    api, listed_total = 0.0, 0.0
    for model, tokens_in, tokens_out, cache_read, cache_write, cost, provider, source in rows:
        listed = list_cost(str(model or ""), tokens_in=int(tokens_in or 0), tokens_out=int(tokens_out or 0),
                           cache_read=int(cache_read or 0), cache_write=int(cache_write or 0))
        priced = listed if _family(str(model or "")) else float(cost or 0)
        if _seat(provider, source):
            listed_total += priced  # costs the platform nothing: shown as the API equivalent, never enforced
        else:
            api += float(cost or 0) or priced
    _spend_cache[run.id] = (time.monotonic(), (api, listed_total))
    return api, listed_total


def _seat(provider: Any, source: Any) -> bool:
    return str(source or "") == "seat_subscription" or str(provider or "").endswith("_seat")


def run_budget(run: WorkflowRun) -> float:
    budget = dict(dict(run.limits or {}).get("budget") or {})
    value = budget.get(BUDGET_KEY)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) and value > 0 \
        else DEFAULT_RUN_BUDGET_USD


def _paused_for_budget(run: WorkflowRun) -> bool:
    from ..states import PAUSE_BUDGET_LIMIT, STATUS_PAUSED

    return run.status == STATUS_PAUSED and run.pause_reason == PAUSE_BUDGET_LIMIT


@dataclass(frozen=True)
class GuardResult:
    body: dict[str, Any]
    refusal: str = ""
    hint: str = ""


async def _pause_for_budget(db: AsyncSession, run: WorkflowRun, spent: float, budget: float) -> None:
    from ..limits import pause_run
    from ..records import lock_run
    from ..states import ACTIVE_STATUSES, PAUSE_BUDGET_LIMIT, STATUS_PAUSED

    run = await lock_run(db, run)
    if run.status not in ACTIVE_STATUSES or run.status == STATUS_PAUSED:
        return
    limits = dict(run.limits or {})
    budget_limits, ceiling = dict(limits.get("budget") or {}), dict(limits.get("budget_ceiling") or {})
    budget_limits.setdefault(BUDGET_KEY, budget)
    ceiling.setdefault(BUDGET_KEY, budget * BUDGET_CEILING_FACTOR)  # "Continue with more budget" may raise it
    run.limits = {**limits, "budget": budget_limits, "budget_ceiling": ceiling}
    run.budget_usage = {**dict(run.budget_usage or {}), USAGE_KEY: round(spent, 4)}
    await pause_run(db, run, reason=PAUSE_BUDGET_LIMIT, actor_id=None, detail={
        "keys": [BUDGET_KEY], "spent_usd": round(spent, 4), "budget_usd": round(budget, 4),
        "message": (f"The run used ${spent:.2f} of API model calls, its budget is ${budget:.2f}; the "
                    "platform stopped its sessions. Continue with more budget, change the plan, or abort."),
        "resume": {"kind": "stay"},
    })
    await db.commit()


async def _note_mapping(db: AsyncSession, run: WorkflowRun, requested: str, model: str) -> None:
    from ..records import record_event

    context = dict(run.context or {})
    seen = list(context.get(EVENT_MODEL_MAPPED) or [])
    if requested in seen:
        return
    run.context = {**context, EVENT_MODEL_MAPPED: [*seen, requested][:50]}
    record_event(db, run, EVENT_MODEL_MAPPED, node_id=run.current_node_id,
                 detail={"requested": requested[:120], "ran": model[:120],
                         "why": "a model above the run's own models; the call ran on the phase's model"})
    await db.commit()


async def guard_model_call(db: AsyncSession, session_id: str, body: dict[str, Any],
                           field: str = "model", *, engine: str = "") -> GuardResult:
    # On the Codex path only Codex's own models are compared, so a Claude model never lands on it.
    from ..records import active_run_for_session

    run = await active_run_for_session(db, session_id)
    if run is None:
        return GuardResult(body)
    budget = run_budget(run)
    if _paused_for_budget(run):
        return GuardResult(body, REASON_RUN_BUDGET, _budget_hint(budget))
    spent, equivalent = await run_costs(db, run)
    if spent >= budget:
        await _pause_for_budget(db, run, spent, budget)
        return GuardResult(body, REASON_RUN_BUDGET, _budget_hint(budget))
    if equivalent >= budget and not dict(run.context or {}).get(EVENT_SEAT_EQUIVALENT):
        await _note_seat_equivalent(db, run, equivalent, budget)
    requested = str(body.get(field) or "").strip()
    replacement = (await _models_for(db, run)).replacement(requested, engine=engine)
    if replacement is None or replacement == requested:
        return GuardResult(body)
    await _note_mapping(db, run, requested, replacement)
    return GuardResult({**body, field: replacement})


def _budget_hint(budget: float) -> str:
    return (f"The workflow run reached its model budget (${budget:.2f} of API cost) and is paused until a person "
            "decides. End your turn.")


async def _note_seat_equivalent(db: AsyncSession, run: WorkflowRun, equivalent: float, budget: float) -> None:
    from ..records import lock_run, record_event

    run = await lock_run(db, run)
    if dict(run.context or {}).get(EVENT_SEAT_EQUIVALENT):
        return
    run.context = {**dict(run.context or {}), EVENT_SEAT_EQUIVALENT: round(equivalent, 4)}
    run.budget_usage = {**dict(run.budget_usage or {}), USAGE_KEY: round(equivalent, 4)}
    record_event(db, run, EVENT_SEAT_EQUIVALENT, node_id=run.current_node_id, detail={
        "list_cost_usd": round(equivalent, 4), "budget_usd": round(budget, 4),
        "message": (f"The run's seat calls would have cost ${equivalent:.2f} via the API (list price), its budget "
                    f"is ${budget:.2f}. Seat calls cost the platform nothing; the run goes on.")})
    await db.commit()


__all__ = ["DEFAULT_RUN_BUDGET_USD", "ENGINE_CODEX", "EVENT_MODEL_MAPPED", "REASON_RUN_BUDGET", "GuardResult",
           "RunModels", "codex_tier", "guard_model_call", "list_cost", "model_tier", "run_budget", "run_costs",
           "run_models", "run_spend"]
