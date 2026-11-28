"""The prompt of a continuation turn: the phase it starts, what changed for a resumed pass, a new story of an epic."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..graph import NODE_PHASE, PhasedNode
from ..run_texts import run_text


def _prompt(run: WorkflowRun, node: PhasedNode, *, resumed: bool = False, retry: bool = False,
            then: PhasedNode | None = None) -> str:
    from ..phase_contract import phase_definition
    from ..pipeline import ACTION as PIPELINE_ACTION

    if resumed and node.kind == NODE_PHASE:
        return _resumed_prompt(run, node, retry=retry)
    from ..hands_on.step import ACTION as HANDS_ON_ACTION
    from ..hands_on.step import MODE_REPRODUCE

    if resumed and then is not None and then.kind == NODE_PHASE and node.config.get("action") == PIPELINE_ACTION:
        return _pipeline_red_prompt(run, then)
    if (resumed and then is not None and then.kind == NODE_PHASE and node.config.get("action") == HANDS_ON_ACTION
            and node.config.get("mode") != MODE_REPRODUCE):
        # The launcher runs the hands-on test before the agent starts and starts none when it is green: the agent of
        # this turn only ever reads this after a red test, in the building phase's session (``_following_phase``).
        # The bug flow's reproduce check uses the same action, but there red is the expected result, not a failure.
        return run_text("hands_on_red", phase=then.title, run_id=run.id)
    if node.kind != NODE_PHASE:
        return run_text("continue_prepared", workflow_key=run.workflow_key, step=node.title or node.id,
                        read_contract=read_contract(run))
    from .gate_failure import back_prompt

    if back := back_prompt(run, node, read_contract(run)):
        return back
    contract = dict(phase_definition(run, node).get("workflow_contract") or {})
    prompt = run_text("continue_phase", workflow_key=run.workflow_key, phase=node.title,
                      capability_class=contract.get("capability_class") or "read_only",
                      read_contract=read_contract(run))
    note = _change_plan_note(run, node)
    return f"{prompt} {note[:1].upper()}{note[1:]}." if note else prompt


def _change_plan_note(run: WorkflowRun, node: PhasedNode) -> str:
    reason = dict(dict(getattr(run, "context", None) or {}).get("change_plan_reason") or {})
    if not reason or reason.get("shown") or node.kind != NODE_PHASE:
        return ""
    run.context = {**dict(run.context or {}), "change_plan_reason": {**reason, "shown": True}}
    return run_text("changed.change_plan", from_phase=reason.get("from") or "", intent=reason.get("intent") or "",
                    refusal=str(reason.get("refusal") or reason.get("reason") or "")[:300])


def _pipeline_red_prompt(run: WorkflowRun, phase: PhasedNode) -> str:
    # The launcher starts no agent when the pipeline is green, so this prompt is only read after a red pipeline.
    return run_text("pipeline_red", phase=phase.title, run_id=run.id)


def read_contract(run: WorkflowRun) -> str:
    return run_text("read_contract", run_id=run.id)


CHANGED_FIELDS = ("pipeline_failure", "hands_on_failure", "product_owner_answers", "review_findings", "findings")


def _phase_facts(run: WorkflowRun, node: PhasedNode) -> dict:
    from ..phase_contract import phase_definition
    from ..phase_marker import RUN_PHASE_CONTRACT_KEY

    return dict(dict(phase_definition(run, node).get("workflow_contract") or {}).get(RUN_PHASE_CONTRACT_KEY) or {})


def _what_changed(run: WorkflowRun, node: PhasedNode) -> str:
    facts = _phase_facts(run, node)
    changed = [run_text(f"changed.{name}") for name in CHANGED_FIELDS if facts.get(name)]
    if note := _change_plan_note(run, node):
        changed.insert(0, note)
    from .gate_failure import current

    if (found := current(run, node.id)) is not None:
        changed.insert(0, run_text("changed.gate_failed", gate=found.get("gate") or "",
                                   failed=found.get("failed") or ""))
    return "; ".join(changed) or run_text("changed.none")


def _epic_prompt(run: WorkflowRun, node: PhasedNode) -> str:
    return run_text("epic_next_story", phase=node.title, workflow_key=run.workflow_key, run_id=run.id,
                    read_contract=read_contract(run))


async def plain_story_prompt(db: AsyncSession, run: WorkflowRun, node: PhasedNode, *, epic: bool) -> str:
    from ..phase_contract import phase_definition
    from ..workspace.spec import environment_for_run
    from .contract import _work_item, environment_file_note, plain_brief

    if node.kind != NODE_PHASE or not plain_brief(node):
        return ""
    item = await _work_item(db, run) or {}
    environment = dict(await environment_for_run(db, run) or {})
    tests = [f"`{environment[key]}`" for key in ("test", "system_test") if str(environment.get(key) or "").strip()]
    brief = str(dict(phase_definition(run, node).get("workflow_contract") or {}).get("when_to_use") or "")
    note = environment_file_note(environment)
    return run_text("plain_story", lead=run_text("plain_story.epic_lead") if epic else "", run_id=run.id,
                    key=item.get("key") or "", title=item.get("title") or "", description=item.get("description") or "",
                    tests=f"{note}\n\n" if note else run_text("plain_story.tests", commands=" and ".join(tests))
                    if tests else "", brief=brief)


def _resumed_prompt(run: WorkflowRun, node: PhasedNode, *, retry: bool) -> str:
    if retry:
        return run_text("resumed_retry", phase=node.title, run_id=run.id)
    import json

    facts = _phase_facts(run, node)
    details = {name: facts[name] for name in CHANGED_FIELDS if facts.get(name)}
    prompt = run_text("resumed", phase=node.title, run_id=run.id, what_changed=_what_changed(run, node))
    if not details:
        return run_text("resumed.ask", resumed=prompt)
    # The changed fields themselves, whole: a status call would fetch the whole contract again into a large session.
    return run_text("resumed.details", resumed=prompt, details=json.dumps(details, ensure_ascii=False, indent=1))
