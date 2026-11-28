"""The contract an item's session follows: its role's phase, narrowed to the item."""

from __future__ import annotations

import copy
from typing import Any

from ..graph import NODE_PHASE, PhasedNode
from ..phase_marker import RUN_PHASE_CONTRACT_KEY
from . import ITEM_RESULT_VALUES, work_of
from .node import roles_of
from .plan import write_paths

ITEM_RULE = (
    "You build one item of a story the coordinator split between several agents working at the same time. Change "
    "only the files under your paths; another item owns everything else. Follow the shared contract exactly (API "
    "shapes, component names, test ids), so the items fit together when they are merged. Write your proof tests "
    "under exactly the named file and function. When the item is built, end with submit_phase_result value \"done\" "
    "and a one-line summary. If you cannot go on without a change outside your paths or a decision you cannot make, "
    "do not wait and do not edit other paths: end with submit_phase_result value \"blocked\" and say exactly what you "
    "need; the coordinator re-plans."
)


def appends_rule() -> str:
    from ..run_texts import run_text

    return run_text("item.appends_rule")


FIX_RULE = (
    "The CI pipeline ran the whole merged story and these failures lie in your item's files. Fix exactly them in your "
    "paths (the code when it deviates from the contract, the test only when the test is wrong), run the named tests, "
    "then finish with submit_phase_result \"done\". Every other item stays merged and is not built again. If the "
    "cause lies in another item's files, finish with \"blocked\" and name the file and the item."
)


REVIEW_FIX_RULE = (
    "The independent review of the whole merged story found these points in your item's files. Fix exactly them in "
    "your paths as the finding says, keep everything else as it is, run your tests, then finish with "
    "submit_phase_result \"done\". Every other item stays merged and is not built again. If a finding needs "
    "another item's files, finish with \"blocked\" and name the file and the item."
)


def item_node(run: Any, node: PhasedNode, item: dict[str, Any]) -> PhasedNode:
    config = copy.deepcopy(roles_of(node).get(str(item.get("role") or "")) or {})
    config.pop("needs_proof", None)
    config.pop("starts_at_once", None)
    contract = dict(config.get("workflow_contract") or {})
    rules = dict(contract.get("path_rules") or {})
    rules["write"] = write_paths(item)
    contract["path_rules"] = rules
    config["workflow_contract"] = contract
    config["result_values"] = list(ITEM_RESULT_VALUES)
    from ..phase_contract import ITEM_ITERATION_KEY, ITEM_TASKS_KEY

    config[ITEM_ITERATION_KEY] = int(item.get("iteration") or 1)
    config[ITEM_TASKS_KEY] = [item_task(item)] if item.get("proofs") else []
    if item.get("model"):
        config["model"] = str(item["model"])
    config["title"] = str(item.get("title") or item.get("id") or "")
    return PhasedNode(node.id, NODE_PHASE, f"{node.title} · {item.get('title') or item.get('id')}", config)


def item_task(item: dict[str, Any]) -> dict[str, Any]:
    proofs = [str(proof) for proof in item.get("proofs") or []]
    return {"id": str(item.get("id") or ""), "text": str(item.get("title") or ""), "proof": proofs[0] if proofs else "",
            "proofs": proofs, "roles": [str(item.get("role") or "")]}


def team_view(run: Any) -> list[dict[str, Any]]:
    items = dict(work_of(run).get("items") or {})
    return [{"id": key, "role": value.get("role"), "title": value.get("title"), "status": value.get("status"),
             "paths": list(value.get("paths") or []), "depends_on": list(value.get("depends_on") or []),
             **({"agent_hash": value["agent_hash"]} if value.get("agent_hash") else {})}
            for key, value in sorted(items.items())]


def item_definition(run: Any, node: PhasedNode, item: dict[str, Any]) -> dict[str, Any]:
    from ..phase_contract import phase_definition

    synthetic = item_node(run, node, item)
    definition = phase_definition(run, synthetic)
    contract = dict(definition.get("workflow_contract") or {})
    facts = dict(contract.get(RUN_PHASE_CONTRACT_KEY) or {})
    work = work_of(run)
    facts["iteration"] = int(item.get("iteration") or 1)
    facts["work_item"] = {"id": item.get("id"), "title": item.get("title"), "role": item.get("role"),
                          "instructions": item.get("instructions"), "paths": list(item.get("paths") or []),
                          "depends_on": list(item.get("depends_on") or []), "rule": ITEM_RULE,
                          **({"appends_to": list(item["appends_to"]), "appends_rule": appends_rule()}
                             if item.get("appends_to") else {})}
    if work.get("contract"):
        facts["shared_contract"] = work["contract"]
    facts["team"] = {"coordinator": work.get("coordinator_hash"), "items": team_view(run)}
    if item.get("proofs"):
        from ..task_list import BUILD_RULE

        facts["task_list"] = [item_task(item)]
        facts["task_list_rule"] = BUILD_RULE
    else:
        facts.pop("task_list", None)
        facts.pop("task_list_rule", None)
    if item.get("reason") and int(item.get("iteration") or 1) > 1:
        facts["findings"] = [*(facts.get("findings") or []), f"This item was sent back to you: {item['reason']}"]
    if item.get("fix") and int(item.get("iteration") or 1) > 1:
        # A targeted fix (``teamwork.fixes``): exactly what failed in this item's part (with its output), or the
        # review's findings in its files.
        if item.get("fix_source") == "review":
            facts["review_fix"] = {"rule": REVIEW_FIX_RULE, "findings": list(item["fix"])}
        else:
            facts["pipeline_fix"] = {"rule": FIX_RULE, "failures": list(item["fix"])}
    contract[RUN_PHASE_CONTRACT_KEY] = facts
    definition["workflow_contract"] = contract
    return definition


async def session_item_node(db: Any, run: Any, node: PhasedNode,
                            session_id: str | None) -> PhasedNode | None:
    from ....models import Session
    from . import item_key_of, session_works_on

    session = await db.get(Session, session_id) if session_id else None
    item = dict(dict(work_of(run).get("items") or {}).get(item_key_of(session) or "") or {})
    if not session_works_on(run, item, session):
        return None
    return item_node(run, node, item)


__all__ = ["ITEM_RULE", "item_definition", "item_node", "item_task", "session_item_node", "team_view"]
