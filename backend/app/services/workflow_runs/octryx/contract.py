"""The run contract v2 an octryx-claude session follows: the run's current state as data."""

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
    from ..workspace.spec import ENVIRONMENT_FILE_FORMAT

    if not isinstance(environment, dict) or not environment.get("environment_file"):
        return ""
    file, folder = environment["environment_file"], environment.get("app_folder") or "."
    return _text("environment_file", file=file, format=ENVIRONMENT_FILE_FORMAT, folder=folder)


def environment_file_rule(capability_class: str, environment: Any) -> dict[str, Any] | None:
    from .system_tests import CHANGING

    note = environment_file_note(environment) if capability_class in CHANGING else ""
    return {"file": environment["environment_file"], "app_folder": environment.get("app_folder") or ".",
            "rule": note} if note else None


def _next(graph: Any, node: Any) -> list[str]:
    following = [graph.nodes[edge.target] for edge in graph.exits(node.id) if edge.target in graph.nodes]
    return [str(check.get("description") or check.get("type") or "")
            for gate in following if gate.kind == NODE_GATE
            for check in gate.config.get("checks") or [] if isinstance(check, dict)]


async def session_principal(db: AsyncSession, session: Any) -> Any:
    # The hook's actual caller, never the run's requester.
    from ..work_roles import active_human

    user_id = str(getattr(session, "user_id", None) or "")
    return await active_human(db, user_id) if user_id else None


async def _work_item(db: AsyncSession, run: WorkflowRun) -> dict[str, Any] | None:
    from ....models.runtime.secure_work import WorkItem

    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    if item is None:
        return None
    description = str(item.description or "")
    return {"key": item.source_key, "title": item.title, "issue_type": item.issue_type,
            "description": description}  # never cut: an artificial limit loses real content


def _session_node(run: WorkflowRun, session: Any, graph: Any) -> tuple[Any, Any, Any, bool]:
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
        # A platform Work item has no ticket key, so the run's Work item is part of its contract.
        "work_item": await _work_item(db, run),
        "preparation": item_preparation(run, session, contract_view(run)),
        "pipeline": pipeline_view(run),
        "hands_on": hands_on_view(run),
    }



async def _with_run_extras(db: AsyncSession, run: WorkflowRun, contract: dict[str, Any], *, item: Any, idle: Any,
                           woken: bool) -> None:
    from ..teamwork.item_sessions import item_contract
    from ..teamwork.work_git import contract_view as work_git_view

    if contract["phase"] is not None and contract["phase"].get("how_to_run_tests"):
        await with_test_runs(db, run, contract)
    if contract["pipeline"] is not None:
        from ..run_texts import launcher_texts

        contract["prompt_texts"] = await launcher_texts(db, run)
    from ..workspace.contract_pin import view as pin_view

    if (pinned := pin_view(run)) is not None:
        contract["environment_pin"] = pinned  # the launcher's facts use the run's contract, not the working tree
    if idle is not None:
        contract["item_idle"] = idle  # the item's session ends its turn; its work stays in its folder
    if item is None and idle is None and (git_work := work_git_view(run)) is not None:
        contract["work_git"] = git_work
    if item is not None and contract["phase"] is not None:
        contract["phase"]["work_item"] = await item_contract(db, run, item)
    if woken and contract["phase"] is not None:
        contract["phase"]["coordinator_wake"] = True  # its Stop ends the turn; the node goes on without it



async def run_contract(db: AsyncSession, run: WorkflowRun, *, principal=None, session=None) -> dict[str, Any]:
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

    contract[PATHS_KEY] = list(DETAIL_PATHS)
    contract["digest"] = "sha256:" + sha256(json.dumps(contract, sort_keys=True, default=str).encode()).hexdigest()
    return contract


PLAIN_BRIEF = "plain"
# The Engineer agent's way of working stays out of a plain story session.


def plain_brief(node: Any) -> bool:
    return isinstance(getattr(node, "config", None), dict) and node.config.get("brief") == PLAIN_BRIEF


def plain_agent(agent: dict[str, Any] | None) -> dict[str, Any] | None:
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
        # Only the loops the run took: a loop never taken would read as the reason the agent is back.
        loops = "; ".join(f"{loop['title']} {loop['iteration']}/{loop['of']}" for loop in contract.get("loop") or []
                          if int(loop.get("iteration") or 1) > 1)
        return (f"Workflow run {run.get('workflow_key')}: phase '{phase['title']}' ({phase['capability_class']})"
                f"{'; ' + loops if loops else ''}.")
    return f"Workflow run {run.get('workflow_key')}: {run.get('status')}."


__all__ = ["CONTRACT_VERSION", "contract_summary", "run_contract", "run_link"]
