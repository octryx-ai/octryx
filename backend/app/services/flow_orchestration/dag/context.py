"""State shared by the node loop, and the per-entry-point differences it honours."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import FlowNodeRun
from ....models.agent.orchestrator_agent import OrchestratorAgentRun
from ...flow_runtime_governance import FlowRuntimeLimits, FlowRuntimeUsage
from .graph import FlowGraph


@dataclass(frozen=True)
class LoopMode:
    """What differs between a fresh run, a resume after approval and a resume after an interruption.

    The three entry points share one node loop; their audit details, acceptance reasons and checkpoint
    behaviour stay exactly as each entry point has always recorded them.
    """

    # Extra key merged into failure details and run_failed audit details (empty for a fresh run).
    detail: dict[str, Any]
    # Progress phase recorded when the loop picks up a node.
    start_phase: str
    skip_reason: str
    # Inserted into "Node X failed<suffix>: ..." on a node failure.
    error_suffix: str
    # Commit after each skipped/completed node and on a node stop; otherwise only flush on a stop.
    commit_each_node: bool
    # Commit (rather than flush) when the node-count or run-duration limit stops the run.
    commit_on_limit_stop: bool
    # Report a runtime-limit error raised by a node as budget_exceeded instead of a plain node failure.
    catch_node_limits: bool
    check_validation: bool
    # Number a node's attempt after the attempts already recorded for it.
    count_attempts: bool
    # Acceptance reasons; None means that stop records no acceptance change.
    node_count_reason: str | None
    run_limit_reason: str | None
    paused_reason: str
    node_limit_reason: str | None
    node_failed_reason: str


@dataclass
class DagRun:
    """One pass over a flow graph: the run, its runtime budget and what the nodes produced so far."""

    db: AsyncSession
    run: OrchestratorAgentRun
    version: Any
    graph: FlowGraph
    mode: LoopMode
    user_id: str
    agent_type: str
    project_id: str | None
    project_config: dict[str, Any]
    limits: FlowRuntimeLimits
    usage: FlowRuntimeUsage
    initial_input: dict[str, Any]
    outputs: dict[str, dict[str, Any]]
    skipped: set[str]
    previous_node_runs: list[FlowNodeRun] = field(default_factory=list)
    # Nodes that already have a row and are passed over (resume after approval only).
    existing_node_ids: set[str] = field(default_factory=set)
    final_output: dict[str, Any] = field(default_factory=dict)
