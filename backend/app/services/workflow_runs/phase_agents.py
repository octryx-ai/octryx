"""The phase names its agent.

``phase.config.agent`` is the one home of "which agent runs a phase": a platform agent key (``assistant`` or
``engineer``) whose ceiling covers the phase's class. The ``review`` node's agent is fixed by its kind (the
Reviewer); slice children default to their phase's agent. A phase without ``agent`` holds its turn with
``needs_configuration`` (``phase_agent_binding.py``).

Two checks: the static one at validation (closed vocabulary, the shipped ceilings) and the one against the database
at publish and run start (the agent exists, is active, is not retired, has a published revision whose ceiling covers
the class — the live row's content never counts).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..platform_agents.catalog import ASSISTANT, ENGINEER, ceiling_covers
from ..platform_agents.published import PublishedPlatformAgent, published_agent_refusal, published_platform_agent
from ..platform_agents.seeds import SEEDS_BY_KEY
from .graph import NODE_PHASE, NODE_REVIEW, PhasedGraph, parse_phased_definition

PHASE_AGENT_KEYS: tuple[str, ...] = (ASSISTANT, ENGINEER)
AGENT_KEY = "agent"


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def phase_agent_key(config: dict[str, Any]) -> str:
    return str(config.get(AGENT_KEY) or "").strip()


def phase_class(config: dict[str, Any]) -> str:
    contract = config.get("workflow_contract") if isinstance(config.get("workflow_contract"), dict) else {}
    return str(contract.get("capability_class") or "read_only")


def static_phase_agent_errors(graph: PhasedGraph, *, require: bool = False) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for node in graph.nodes.values():
        if node.kind == NODE_REVIEW and AGENT_KEY in node.config:
            errors.append(_error("review_agent_fixed", f"Review '{node.id}' always runs as the Reviewer; it names "
                                                       "no agent."))
        if node.kind != NODE_PHASE:
            continue
        key = phase_agent_key(node.config)
        if not key:
            if require:
                errors.append(_error("phase_without_agent", f"Phase '{node.id}' must name its agent "
                                                            f"({', '.join(PHASE_AGENT_KEYS)})."))
            continue
        if key not in PHASE_AGENT_KEYS:
            errors.append(_error("phase_agent_unknown", f"Phase '{node.id}' names agent '{key}'; a phase runs as "
                                                        f"one of: {', '.join(PHASE_AGENT_KEYS)}."))
            continue
        if not ceiling_covers(SEEDS_BY_KEY[key].capability_ceiling, phase_class(node.config)):
            errors.append(_error("phase_agent_ceiling", f"Phase '{node.id}' is {phase_class(node.config)}; the "
                                                        f"agent '{key}' may not run it."))
        sub = node.config.get("sub_agents")
        sub_agent = str(sub.get(AGENT_KEY) or "").strip() if isinstance(sub, dict) else ""
        if sub_agent and sub_agent != key:
            errors.append(_error("sub_agent_mismatch", f"Phase '{node.id}': slice children run as the phase's "
                                                       f"agent '{key}', not '{sub_agent}'."))
    return errors


async def platform_agent(db: AsyncSession, key: str) -> PublishedPlatformAgent | None:
    """The platform agent as its published revision defines it (never the live row's content)."""
    return await published_platform_agent(db, key)


def agent_refusal(agent: PublishedPlatformAgent | None, *, needed_class: str = "read_only") -> str:
    """``""`` when the agent can run, else the typed reason (``agent_unpublished`` included)."""
    return published_agent_refusal(agent, needed_class=needed_class)


async def phase_agent_db_errors(db: AsyncSession, definition: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    graph = parse_phased_definition(definition)
    for node in graph.nodes.values():
        key = phase_agent_key(node.config) if node.kind == NODE_PHASE else ""
        if key not in PHASE_AGENT_KEYS:
            continue
        reason = agent_refusal(await platform_agent(db, key), needed_class=phase_class(node.config))
        if reason:
            errors.append(_error("phase_agent_unavailable", f"Phase '{node.id}': agent '{key}' cannot run it "
                                                            f"({reason})."))
    return errors


async def with_phase_agent_errors(db: AsyncSession, definition: dict[str, Any], report: dict[str, Any]
                                  ) -> dict[str, Any]:
    if str(definition.get("execution_kind") or "") != "phased":
        return report
    extra = await phase_agent_db_errors(db, definition)
    if not extra:
        return report
    return {**report, "valid": False, "errors": [*report.get("errors", []), *extra]}
