"""The contract a phase turn follows: the phase's inline definition plus the run facts."""

from __future__ import annotations

from typing import Any

from ...models import WorkflowRun
from ..workflow_checks.library import FAILED as CHECK_FAILED
from .graph import PhasedNode
from .phase_marker import RUN_PHASE_CONTRACT_KEY

WARNINGS_RULE = ("code_style_warnings never block and are not this phase's task: fix one only in lines you change "
                 "anyway. The phase is done when its checks pass (the tests after your last change first).")
ITEM_ITERATION_KEY = "item_iteration"
# A teamwork item's synthetic phase carries its own task (``item_definition.item_node``): its proofs, never the
# other items' of the same role.
ITEM_TASKS_KEY = "item_tasks"


def _context(run: WorkflowRun) -> dict[str, Any]:
    return dict(run.context or {})


def phase_definition(run: WorkflowRun, node: PhasedNode) -> dict[str, Any]:
    config = dict(node.config)
    # A teamwork item's synthetic phase names its own pass (``item_definition.item_node``): on its first pass it is new
    # work, never a rework of the story's earlier change.
    item_iteration = config.pop(ITEM_ITERATION_KEY, None)
    item_tasks = config.pop(ITEM_TASKS_KEY, None)
    contract = dict(config.get("workflow_contract") or {})
    carried = dict(dict(_context(run).get("carried") or {}).get(node.id) or {})
    findings = [
        str(item.get("description") or item.get("type") or "")
        for item in (dict(carried.get("result") or {}).get("results") or [])
        if isinstance(item, dict) and item.get("outcome") == CHECK_FAILED
    ]
    contract[RUN_PHASE_CONTRACT_KEY] = {
        "title": node.title,
        "iteration": int(item_iteration or dict(run.node_state or {}).get("iteration") or 1),
        "findings": [item for item in findings if item],
    }
    from .phase_outputs import OUTPUT_SPECS, available_inputs, phase_inputs, phase_output

    inputs = available_inputs(run, phase_inputs(node))
    if inputs:
        contract[RUN_PHASE_CONTRACT_KEY]["inputs"] = inputs
    if phase_output(node) in OUTPUT_SPECS:
        spec = OUTPUT_SPECS[phase_output(node)]
        contract[RUN_PHASE_CONTRACT_KEY]["output"] = {"kind": spec.kind, "tool": spec.tool}
    from .conditions import declared_result_values
    from .phase_outputs import RESULT_TOOL

    results = list(declared_result_values(node.config))
    if results:
        contract[RUN_PHASE_CONTRACT_KEY]["result"] = {"tool": RESULT_TOOL, "values": results}
        contract["checks"] = [*(contract.get("checks") or []), {
            "type": "tool_called", "params": {"tools": [RESULT_TOOL]}, "blocking": True,
            "description": f"Result recorded with {RESULT_TOOL} (one of: {', '.join(results)})"}]
        policy = dict(config.get("tool_policy") or {})
        policy["allowlist"] = list(dict.fromkeys([*(policy.get("allowlist") or []), RESULT_TOOL]))
        config["tool_policy"] = policy
    reviewed = [item for item in (dict(carried.get("result") or {}).get("results") or [])
                if isinstance(item, dict) and item.get("type") in {"review_passed", "artefact_review_passed"}
                and item.get("outcome") == CHECK_FAILED]
    if reviewed:
        from .review.verdict import verdict_from_record

        record = _context(run).get("review")
        if isinstance(record, dict) and record.get("mode") == "artefact":
            from .review.artefact_contract import parse_verdict

            verdict = parse_verdict({key: record.get(key) for key in ("verdict", "summary", "findings")})
        else:
            verdict = verdict_from_record(record)
        contract[RUN_PHASE_CONTRACT_KEY]["review_findings"] = [
            finding.render() for finding in (verdict.findings if verdict is not None else ())]
    from .task_list import BUILD_RULE, for_roles, phase_roles, run_task_list, sets_task_list

    # Team delivery: a role phase (``tasks: "frontend"``) builds only its role's items and the
    # untagged ones; the phase that writes the list (``sets_task_list``) is not given it as its own work, else its
    # Stop would ask it for the builders' proof tests.
    tasks = [] if sets_task_list(config) else for_roles(run_task_list(run), phase_roles(config))
    if item_tasks is not None:
        # A teamwork item builds its own task only, else its Stop asks for the other items' proof tests.
        tasks = [dict(task) for task in item_tasks if isinstance(task, dict)]
    if tasks and str(contract.get("capability_class") or "") in ("change", "deliver"):
        contract[RUN_PHASE_CONTRACT_KEY]["task_list"] = tasks
        contract[RUN_PHASE_CONTRACT_KEY]["task_list_rule"] = BUILD_RULE
    if str(contract.get("capability_class") or "") in ("change", "deliver") and _context(run).get(
            "code_style_warnings"):
        contract[RUN_PHASE_CONTRACT_KEY]["code_style_warnings"] = str(_context(run)["code_style_warnings"])
        contract[RUN_PHASE_CONTRACT_KEY]["code_style_warnings_rule"] = WARNINGS_RULE
    if str(contract.get("capability_class") or "") in ("change", "deliver"):
        from .pipeline_failure import failure_for_agent

        if red := failure_for_agent(run):
            contract[RUN_PHASE_CONTRACT_KEY]["pipeline_failure"] = red
        from .hands_on.step import failure_for_agent as hands_on_failure

        if red := hands_on_failure(run):
            contract[RUN_PHASE_CONTRACT_KEY]["hands_on_failure"] = red
        from .evidence_pause import rerun_hint

        if hint := rerun_hint(run, str(getattr(run, "current_node_id", None) or "")):
            contract[RUN_PHASE_CONTRACT_KEY]["test_evidence_hint"] = hint
        from .size_class.steps import agent_facts

        if size := agent_facts(run):
            contract[RUN_PHASE_CONTRACT_KEY]["size_class"] = size
    if bug := _context(run).get("bug_report"):
        contract[RUN_PHASE_CONTRACT_KEY]["bug_report"] = bug
    answers = [dict(item) for item in _context(run).get("po_answers") or []
               if isinstance(item, dict) and not item.get("replaced_by")]
    if answers and item_iteration != 1:
        # A first-pass item is new work: the story's auto-accept answers and earlier change would read as a rework.
        contract[RUN_PHASE_CONTRACT_KEY]["product_owner_answers"] = [str(item.get("text") or "") for item in answers]
        if not reviewed:
            from .review.verdict import verdict_from_record

            verdict = verdict_from_record(_context(run).get("review"))
            if verdict is not None:
                contract[RUN_PHASE_CONTRACT_KEY]["review_findings"] = [item.render() for item in verdict.findings]
                contract[RUN_PHASE_CONTRACT_KEY]["review_assumptions"] = list(verdict.assumptions)
        # The pass's own change, else the one the engine kept when this pass started (a new pass clears device_change).
        patch = str(dict(_context(run).get("device_change") or {}).get("patch") or "") or str(
            dict(_context(run).get("previous_device_change") or {}).get("patch") or "")
        if patch.strip():
            contract[RUN_PHASE_CONTRACT_KEY]["previous_change"] = previous_change(patch)
    config["workflow_contract"] = contract
    from .path_rules import PATH_UNCHECKED_TOOLS, has_path_rules

    if has_path_rules(config):
        # Shell writes bypass the path decision: never offered while path rules apply (also refused at publish).
        policy = dict(config.get("tool_policy") or {})
        policy["denylist"] = sorted({*(policy.get("denylist") or []), *PATH_UNCHECKED_TOOLS})
        policy["allowlist"] = [item for item in policy.get("allowlist") or [] if item not in PATH_UNCHECKED_TOOLS]
        config["tool_policy"] = policy
    return config


# A follow-up pass gets its own change instead of re-orienting from scratch.
MAX_PREVIOUS_PATCH = 12_000
PREVIOUS_CHANGE_NOTE = (
    "The working folder still holds this change from your earlier pass (the patch is against the run's base). Do not "
    "read whole files or list the repository again to orient yourself: work from this patch, and open only the parts "
    "the product owner answers and the review findings name, with Grep or with Read and an offset and limit."
)


def previous_change(patch: str) -> dict:
    import re

    files = list(dict.fromkeys(re.findall(r"^diff --git a/(\S+) b/", patch, flags=re.MULTILINE)))
    small = len(patch) <= MAX_PREVIOUS_PATCH
    return {"files": files, "note": PREVIOUS_CHANGE_NOTE, **({"patch": patch} if small else
                                                            {"patch_omitted": f"{len(patch)} characters"})}


__all__ = ["ITEM_ITERATION_KEY", "ITEM_TASKS_KEY", "MAX_PREVIOUS_PATCH", "phase_definition", "previous_change"]
