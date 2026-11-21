"""The run contract v2 an octryx-claude session follows: the run's current state as data.

``workflow_run_status`` serves it and every hook answer of a bound session carries it, so the model always sees
the **current** phase, never the one at selection time:

- ``run``: id, workflow, version, status, current node, its pass (``entry``);
- ``phase`` (while the run is at a phase): its agent (``agent``: key, name, version, instructions, digest),
  capability class, tools (allow/deny), path rules with the confirmed test files they protect, the phase's checks,
  its instructions, the findings carried back to it, the recorded artefacts it consumes (``inputs``) and the output
  it submits (``output``: kind and tool), and its device continuation
  (``pending`` / ``started`` / ``refused`` with the reason — a refused one is not retried by itself);
- ``loop``: the iteration *i* of *n* of the loops that lead back into the current node;
- ``waiting`` / ``paused``: what the run waits for or why it paused, with the link to the platform;
- ``decision``: who decides it (``decisions.pending_decision``): a requester decision (user confirmation
  or conversation, a pause) is ``in_terminal`` with its payload, payload hash and actions — the user may take it in
  the terminal (``workflow_decide`` + Claude Code's permission prompt) or in the platform; a four-eyes approval or a
  tool approval is platform only; a watched state, the reviewer or a sub-workflow is decided by nobody;
- ``next``: what the following gate needs;
- ``facts``: what the launcher reports at its hooks (confirmed test digests, the change as a diff);
- ``preparation``: the run's branch and the repository's runtime environment (setup, path, probes) the launcher
  prepares its folder for, and the pass it reports for while ``workspace.prepare`` waits (``state: pending``);
- ``digest``: changes whenever any of the above changes (the launcher shows a changed contract once).

The contract describes; it never grants. Every decision is taken again on the server at each hook.
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..graph import NODE_GATE, NODE_PHASE, graph_for_run
from ..hands_on.step import contract_view as hands_on_view
from ..pipeline import contract_view as pipeline_view
from ..workspace.preparation import contract_view
from .continuation_marker import continuation_state
from .contract_phase import _for_codex, _runs_codex, with_decision, with_phase_details, with_test_runs
from .phase_view import _phase, _refresh_device_tools, _text

CONTRACT_VERSION = 2


def _loops(run: WorkflowRun, node_id: str) -> list[dict[str, Any]]:
    return [
        {"edge": edge_id, "title": str(counter.get("title") or edge_id), "iteration": int(counter.get("used") or 0) + 1,
         "of": int(counter.get("limit") or 0) + 1}
        for edge_id, counter in dict(run.loop_counters or {}).items()
        if isinstance(counter, dict) and counter.get("target") == node_id
    ]


def run_link(run: WorkflowRun, session_id: str | None) -> str | None:
    from ...knowledge.episodes.policy import public_origin, session_link

    origin = public_origin()
    return session_link(origin, session_id) if origin and session_id else None


def environment_file_note(environment: Any) -> str:
    """What a building agent is told when the repository record points at an environment file; ``""`` otherwise."""
    from ..workspace.spec import ENVIRONMENT_FILE_FORMAT

    if not isinstance(environment, dict) or not environment.get("environment_file"):
        return ""
    file, folder = environment["environment_file"], environment.get("app_folder") or "."
    return _text("environment_file", file=file, format=ENVIRONMENT_FILE_FORMAT, folder=folder)


def environment_file_rule(capability_class: str, environment: Any) -> dict[str, Any] | None:
    """The ``environment_file`` part of a changing phase's contract, or ``None``."""
    from .system_tests import CHANGING

    note = environment_file_note(environment) if capability_class in CHANGING else ""
    return {"file": environment["environment_file"], "app_folder": environment.get("app_folder") or ".",
            "rule": note} if note else None


def _next(graph: Any, node: Any) -> list[str]:
    """What the gate after the current phase checks (the descriptions), so the agent knows what counts."""
    following = [graph.nodes[edge.target] for edge in graph.exits(node.id) if edge.target in graph.nodes]
    return [str(check.get("description") or check.get("type") or "")
            for gate in following if gate.kind == NODE_GATE
            for check in gate.config.get("checks") or [] if isinstance(check, dict)]


async def session_principal(db: AsyncSession, session: Any) -> Any:
    """The authenticated launcher Session's own active human (a hook's actual caller), never the run's requester."""
    from ..work_roles import active_human

    user_id = str(getattr(session, "user_id", None) or "")
    return await active_human(db, user_id) if user_id else None


async def _work_item(db: AsyncSession, run: WorkflowRun) -> dict[str, Any] | None:
    """The run's Work item as the agent needs it: key, title, type and the description with its criteria."""
    from ....models.runtime.secure_work import WorkItem

    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    if item is None:
        return None
    description = str(item.description or "")
    return {"key": item.source_key, "title": item.title, "issue_type": item.issue_type,
            "description": description}  # never cut: an artificial limit loses real content


def _session_node(run: WorkflowRun, session: Any, graph: Any) -> tuple[Any, Any, Any, bool]:
    """``(node, item, idle, woken)``: the node the session works under, its teamwork item, idle reason and wake."""
    from ..teamwork import work_of
    from ..teamwork.item_sessions import (
        coordinator_wake_of,
        item_idle_reason,
        item_phase_node,
        item_session_key,
        session_item,
    )

    node = graph.nodes.get(run.current_node_id or "")
    item = None
    idle = item_idle_reason(run, session) if session is not None else None
    if session is not None and item_session_key(run, session) is not None and idle is None:
        # An item's session works under its item's phase (the role, its paths, its proofs) at
        # the parallel node, never under the run's current phase; while it has no work (``idle``) it has no phase.
        item = session_item(run, session)
        work_node = graph.nodes.get(str(work_of(run).get("node_id") or ""))
        node = item_phase_node(run, work_node, item) if item is not None and work_node is not None else None
    woken = session is not None and coordinator_wake_of(run, session)
    if woken:
        # The coordinator's board wake: it works under its plan phase (answer, revise the plan).
        node = graph.nodes.get(str(work_of(run).get("plan_node") or "")) or node
    return node, item, idle, woken


async def _base_contract(db: AsyncSession, run: WorkflowRun, graph: Any, node: Any, session: Any, *,
                         state: dict[str, Any], link: str | None, idle: Any) -> dict[str, Any]:
    """The run, its link, phase, loops, gate, facts, Work item, preparation, pipeline and hands-on test."""
    from ..teamwork.item_sessions import item_preparation
    from .browser import phase_allows_browser
    from .research import research_min_sources

    return {
        "version": CONTRACT_VERSION,
        "run": {"id": run.id, "workflow_key": run.workflow_key, "workflow_version": run.workflow_version,
                "status": run.status, "ticket_key": run.ticket_key, "branch": run.branch,
                "current_node": {"id": node.id, "kind": node.kind, "title": node.title} if node else None,
                "entry": state.get("entry"), "entered_at": state.get("entered_at")},
        "link": link,
        "phase": {**_phase(run, node, browser=await phase_allows_browser(db, run, node),
                          research=await research_min_sources(db, run, node)),
                  "continuation": continuation_state(run)}
        if node is not None and node.kind == NODE_PHASE and idle is None else None,
        "loop": _loops(run, run.current_node_id or ""),
        "next": _next(graph, node) if node is not None and node.kind == NODE_PHASE and idle is None else [],
        "waiting": None, "paused": None,
        "facts": {"base_sha": dict(run.context or {}).get("base_sha") or None},
        # a platform Work item has no ticket key; the agent searched the spec for "T11" and
        # never saw the item's acceptance criteria. The run's Work item is part of its contract.
        "work_item": await _work_item(db, run),
        # What the launcher prepares in its folder before the agent starts (``workspace.preparation``).
        "preparation": item_preparation(run, session, contract_view(run)),  # an item's: its own branch
        "pipeline": pipeline_view(run),
        "hands_on": hands_on_view(run),
    }



async def _with_run_extras(db: AsyncSession, run: WorkflowRun, contract: dict[str, Any], *, item: Any, idle: Any,
                           woken: bool) -> None:
    """Test wording, launcher texts, the environment pin and the teamwork parts (idle, git work, item, wake)."""
    from ..teamwork.item_sessions import item_contract
    from ..teamwork.work_git import contract_view as work_git_view

    if contract["phase"] is not None and contract["phase"].get("how_to_run_tests"):
        await with_test_runs(db, run, contract)
    if contract["pipeline"] is not None:
        from ..run_texts import launcher_texts

        # The launcher's texts around a red pipeline, from the prompt catalog (run.launcher.*).
        contract["prompt_texts"] = await launcher_texts(db, run)
    from ..workspace.contract_pin import view as pin_view

    if (pinned := pin_view(run)) is not None:
        contract["environment_pin"] = pinned  # the launcher's facts use the run's contract, not the working tree
    if idle is not None:
        contract["item_idle"] = idle  # the item's session ends its turn; its work stays in its folder
    if item is None and idle is None and (git_work := work_git_view(run)) is not None:
        # The git work the main thread's launcher runs before any agent (teamwork: item worktrees, merges).
        contract["work_git"] = git_work
    if item is not None and contract["phase"] is not None:
        contract["phase"]["work_item"] = await item_contract(db, run, item)
    if woken and contract["phase"] is not None:
        contract["phase"]["coordinator_wake"] = True  # its Stop ends the turn; the node goes on without it



async def run_contract(db: AsyncSession, run: WorkflowRun, *, principal=None, session=None) -> dict[str, Any]:
    """``session``: the session the contract is for; a teamwork item's session sees its item as its phase."""
    from ..records import main_session_id

    graph = await graph_for_run(db, run)
    node, item, idle, woken = _session_node(run, session, graph)
    state = dict(run.node_state or {})
    link = run_link(run, await main_session_id(db, run))
    contract = await _base_contract(db, run, graph, node, session, state=state, link=link, idle=idle)
    await _with_run_extras(db, run, contract, item=item, idle=idle, woken=woken)
    if contract["phase"] is not None:
        await with_phase_details(db, run, graph, node, contract, item=item, principal=principal)
    await with_decision(db, run, contract, state=state, link=link, principal=principal)
    _refresh_device_tools(contract)
    if session is not None and await _runs_codex(db, session):
        _for_codex(contract)
    from .compact_view import DETAIL_PATHS, PATHS_KEY

    contract[PATHS_KEY] = list(DETAIL_PATHS)  # what the launcher leaves out of the agent's view (``compact_view``)
    contract["digest"] = "sha256:" + sha256(json.dumps(contract, sort_keys=True, default=str).encode()).hexdigest()
    return contract


#: ``config.brief: "plain"`` (epic-delivery): the session is plain Claude Code with a plain brief; the platform adds no
#: way of working of its own to the contract.
PLAIN_BRIEF = "plain"
# Otherwise the Engineer agent's "write the tests first, implement the smallest change that makes them pass, and
# split larger work into slices" reaches the story session through the contract; a session then started one
# subagent and waited 745 s for it, where plain Claude Code ran backend and frontend in parallel.


def plain_brief(node: Any) -> bool:
    return isinstance(getattr(node, "config", None), dict) and node.config.get("brief") == PLAIN_BRIEF


def plain_agent(agent: dict[str, Any] | None) -> dict[str, Any] | None:
    """The phase agent with the short instructions of a plain session (its key, name and version stay)."""
    if not isinstance(agent, dict):
        return agent
    instructions = _text("plain_agent")
    digest = "sha256:" + sha256(instructions.encode("utf-8")).hexdigest()
    return {**agent, "instructions": instructions, "digest": digest}


def _where(contract: dict[str, Any], link: str | None) -> str:
    decision = contract.get("decision") or {}
    platform = f"in Octryx{': ' + link if link else ''}"
    if decision.get("in_terminal"):
        return (f"The user decides ({', '.join(decision.get('actions') or [])}) here — ask them, then workflow_decide "
                f"with payload_hash {decision.get('payload_hash')}; they confirm in the permission prompt — or "
                f"{platform}.")
    if decision.get("kind") in ("approval", "tool_approval"):
        return f"Another person or the run card decides {platform}; never here."
    return f"Nobody decides: the run continues by itself ({platform})."


def contract_summary(contract: dict[str, Any]) -> str:
    """One short line for a hook answer or the terminal: the phase, the loop, or what the run waits for."""
    run = contract.get("run") or {}
    if contract.get("item_idle"):
        return (f"{contract['item_idle']} End your turn now: your work stays in your folder and the coordinator "
                "sees it.")
    if contract.get("paused"):
        paused = contract["paused"]
        return (f"Workflow run {run.get('workflow_key')} is paused ({paused.get('reason')}). "
                f"{_where(contract, paused.get('decide_in'))}")
    if contract.get("waiting"):
        waiting = contract["waiting"]
        return (f"Workflow run {run.get('workflow_key')} waits ({waiting.get('kind')}): "
                f"{waiting.get('question') or waiting.get('title') or ''} {_where(contract, waiting.get('decide_in'))}")
    phase = contract.get("phase")
    prep = contract.get("preparation") or {}
    if not phase and prep.get("state") == "pending" and prep.get("runtime") == "terminal":
        return (f"Workflow run {run.get('workflow_key')} waits for its folder's preparation (branch "
                f"{prep.get('branch')}): start octryx-claude again in the repository folder; it prepares the folder "
                "before the agent starts.")
    if phase:
        # Only the loops the run took (: "The reproduce check could not run: back to reproduce 1/3" for a loop
        # never taken read as the reason the agent was back).
        loops = "; ".join(f"{loop['title']} {loop['iteration']}/{loop['of']}" for loop in contract.get("loop") or []
                          if int(loop.get("iteration") or 1) > 1)
        return (f"Workflow run {run.get('workflow_key')}: phase '{phase['title']}' ({phase['capability_class']})"
                f"{'; ' + loops if loops else ''}.")
    return f"Workflow run {run.get('workflow_key')}: {run.get('status')}."


__all__ = ["CONTRACT_VERSION", "contract_summary", "run_contract", "run_link"]
