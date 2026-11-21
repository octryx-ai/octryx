"""Which model and route the independent reviewer of a run uses.

The reviewer is its own session on a model of the run's engine family (``agent_gateway.review_keys``):

- **engine**: the run's own (the engine its device jobs ran on; else the requester's effective engine in the
  Workspace). A Claude Code run is reviewed by a Claude model, a Codex run by a Codex model;
- **model**: the review node's choice (``config.reviewer.<engine>.model``, or the flat ``config.model`` when it is of
  that engine's family) > the Workspace's (``agent_gateway_policy.review.<engine>.model``) > the platform default
  (``agent_gateway/review_models.json``: ``claude-sonnet-5-5`` / ``gpt-6.1-terra``; the installation's
  ``review_defaults`` above them);
- **route**: node > Workspace > the run's own route (a seat run reviews on the seat, any other on a company model).
  A model of neither family (a local Qwen, an alias) runs only when named, and only on the company route.

The chosen model is not a mere preference among the Workspace's runtimes, so a review never silently runs on
whatever is admitted (locally a 9B Qwen stub that times out): the chosen model runs or there is no verdict, with a
clear reason.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import DeviceJob, Project, WorkflowRun, WorkflowRunSession
from ...agent_gateway.engine_keys import ENGINE_CLAUDE_CODE, ENGINES
from ...agent_gateway.review_keys import (
    DEFAULT_MODELS,
    REASON_MODEL_NOT_ON_SEAT,
    REVIEW_KEY,
    ROUTE_COMPANY,
    ROUTE_SEAT,
    ReviewPolicyError,
    model_family,
    normalize_engine_choice,
    normalize_review_section,
)

REASON_CONFIG_INVALID = "needs_configuration:review_config_invalid"
SOURCE_NODE, SOURCE_WORKSPACE, SOURCE_PLATFORM, SOURCE_RUN = "node", "workspace", "platform", "run"
SOURCE_INSTALLATION = "installation"


@dataclass(frozen=True, slots=True)
class ReviewChoice:
    engine: str
    model: str
    route: str
    model_source: str
    route_source: str

    def facts(self) -> dict[str, str]:
        return {f"reviewer_{key}": value for key, value in asdict(self).items()}


async def run_engine(db: AsyncSession, run: WorkflowRun) -> str:
    """The engine the run's device turns ran on; else the requester's effective engine in the Workspace."""
    sessions = select(WorkflowRunSession.session_id).where(WorkflowRunSession.run_id == run.id)
    engine = (await db.execute(
        select(DeviceJob.engine).where(DeviceJob.session_id.in_(sessions), DeviceJob.engine.is_not(None))
        .order_by(DeviceJob.created_at.desc()).limit(1))).scalar_one_or_none()
    if engine in ENGINES:
        return engine
    if run.requested_by and run.project_id:
        from ...agent_gateway.engine_policy import effective_engine

        return (await effective_engine(db, user_id=run.requested_by, workspace_id=run.project_id)).engine
    return ENGINE_CLAUDE_CODE


def run_route(run: WorkflowRun) -> str:
    """The run's own route: a device turn on the seat profile is the seat, everything else the company's models."""
    from ..runtime_target.target import KIND_DEVICE, stored_target

    target = stored_target(run) or {}
    if run.workflow_key == "pr-review-bot":
        # The PR review bot reviews on a person's seat first (``pr_review_bot.seat_choice``),
        # with the visible company fallback when no seat takes it; a node or Workspace route still decides first.
        return ROUTE_SEAT
    return ROUTE_SEAT if target.get("kind") == KIND_DEVICE and target.get("profile") == ROUTE_SEAT else ROUTE_COMPANY


def node_choice(config: dict[str, Any], engine: str) -> dict[str, str]:
    """The review node's own choice for ``engine``; raises :class:`ReviewPolicyError` when it is malformed."""
    section = config.get("reviewer")
    if section is not None:
        per_engine = normalize_review_section(section, "config.reviewer")
        if engine in per_engine:
            return per_engine[engine]
    flat: dict[str, Any] = {}
    model = config.get("model")
    # The flat ``config.model`` counts for its own engine family only.
    if isinstance(model, str) and model.strip() and model_family(model) in (engine, None):
        flat["model"] = model
    if config.get("route") is not None:
        flat["route"] = config["route"]
    return normalize_engine_choice(flat, "config", engine) if flat else {}


async def workspace_choice(db: AsyncSession, project_id: str | None, engine: str) -> dict[str, str]:
    from app.services.agent_gateway.policy_keys import AGENT_GATEWAY_POLICY_CONFIG_KEY

    config = (await db.execute(select(Project.config).where(Project.id == project_id))).scalar_one_or_none() \
        if project_id else None
    stored = config.get(AGENT_GATEWAY_POLICY_CONFIG_KEY) if isinstance(config, dict) else None
    section = stored.get(REVIEW_KEY) if isinstance(stored, dict) else None
    if section is None:
        return {}
    return normalize_review_section(section, f"{AGENT_GATEWAY_POLICY_CONFIG_KEY}.{REVIEW_KEY}").get(engine, {})


async def installation_defaults(db: AsyncSession) -> dict[str, Any]:
    """The platform admins' reviewer defaults (per engine, ``shallow``); a stored value that no longer validates
    raises :class:`ReviewPolicyError` (the review then needs configuration, never silently another model)."""
    import json

    from ...agent_gateway.review_keys import INSTALLATION_KEY, normalize_installation
    from ...system_config.values import get_system_config_value

    raw = await get_system_config_value(db, INSTALLATION_KEY)
    try:
        value = json.loads(raw) if raw else None
    except ValueError as error:
        raise ReviewPolicyError("invalid_review_defaults", INSTALLATION_KEY) from error
    return normalize_installation(value)


async def review_choice(db: AsyncSession, run: WorkflowRun, config: dict[str, Any]) -> ReviewChoice | str:
    """The reviewer's engine, model and route for this run and node, or a fixed refusal reason."""
    engine = await run_engine(db, run)
    try:
        node = node_choice(dict(config or {}), engine)
        workspace = await workspace_choice(db, run.project_id, engine)
        installation = dict((await installation_defaults(db)).get(engine) or {})
    except ReviewPolicyError:
        return REASON_CONFIG_INVALID
    if "model" in node:
        model, model_source = node["model"], SOURCE_NODE
    elif "model" in workspace:
        model, model_source = workspace["model"], SOURCE_WORKSPACE
    elif "model" in installation:
        model, model_source = installation["model"], SOURCE_INSTALLATION
    else:
        model, model_source = DEFAULT_MODELS[engine], SOURCE_PLATFORM
    if "route" in node:
        route, route_source = node["route"], SOURCE_NODE
    elif "route" in workspace:
        route, route_source = workspace["route"], SOURCE_WORKSPACE
    elif "route" in installation:
        route, route_source = installation["route"], SOURCE_INSTALLATION
    else:
        route, route_source = run_route(run), SOURCE_RUN
    if route == ROUTE_SEAT and model_family(model) != engine:
        if route_source != SOURCE_RUN:
            return REASON_MODEL_NOT_ON_SEAT
        route = ROUTE_COMPANY  # a named non-family model of a seat run: only a company runtime can serve it
    return ReviewChoice(engine=engine, model=model, route=route, model_source=model_source, route_source=route_source)


__all__ = ["REASON_CONFIG_INVALID", "ReviewChoice", "node_choice", "review_choice", "run_engine", "run_route",
           "workspace_choice"]
