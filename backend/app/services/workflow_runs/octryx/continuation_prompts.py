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
    if node.kind != NODE_PHASE:  # ``workspace.prepare``: the launcher prepares the folder before the agent starts
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
    """Why a later phase's refusals rule sent the run back to ``node`` (``context.change_plan_reason``), once; ``""``
    otherwise (``run.changed.change_plan``)."""
    reason = dict(dict(getattr(run, "context", None) or {}).get("change_plan_reason") or {})
    if not reason or reason.get("shown") or node.kind != NODE_PHASE:
        return ""
    run.context = {**dict(run.context or {}), "change_plan_reason": {**reason, "shown": True}}
    return run_text("changed.change_plan", from_phase=reason.get("from") or "", intent=reason.get("intent") or "",
                    refusal=str(reason.get("refusal") or reason.get("reason") or "")[:300])


def _pipeline_red_prompt(run: WorkflowRun, phase: PhasedNode) -> str:
    """The prompt of a pipeline turn that resumes the building phase's session. The launcher runs the pipeline before
    the agent starts and starts no agent when it is green, so the agent only ever reads this after a red pipeline."""
    return run_text("pipeline_red", phase=phase.title, run_id=run.id)


def read_contract(run: WorkflowRun) -> str:
    """The sentence that sends the agent to its own run contract (``run.read_contract``)."""
    return run_text("read_contract", run_id=run.id)


CHANGED_FIELDS = ("pipeline_failure", "hands_on_failure", "product_owner_answers", "review_findings", "findings")


def _phase_facts(run: WorkflowRun, node: PhasedNode) -> dict:
    from ..phase_contract import phase_definition
    from ..phase_marker import RUN_PHASE_CONTRACT_KEY

    return dict(dict(phase_definition(run, node).get("workflow_contract") or {}).get(RUN_PHASE_CONTRACT_KEY) or {})


def _what_changed(run: WorkflowRun, node: PhasedNode) -> str:
    """What the platform sends the phase back for, named by the contract fields that carry it."""
    facts = _phase_facts(run, node)
    changed = [run_text(f"changed.{name}") for name in CHANGED_FIELDS if facts.get(name)]
    if note := _change_plan_note(run, node):
        changed.insert(0, note)
    from .gate_failure import current

    if (found := current(run, node.id)) is not None:  # the failed gate first (``octryx.gate_failure``)
        changed.insert(0, run_text("changed.gate_failed", gate=found.get("gate") or "",
                                   failed=found.get("failed") or ""))
    return "; ".join(changed) or run_text("changed.none")


def _epic_prompt(run: WorkflowRun, node: PhasedNode) -> str:
    """The prompt of a phase that resumes its session of the epic's previous story: a new story, same epic."""
    return run_text("epic_next_story", phase=node.title, workflow_key=run.workflow_key, run_id=run.id,
                    read_contract=read_contract(run))


async def plain_story_prompt(db: AsyncSession, run: WorkflowRun, node: PhasedNode, *, epic: bool) -> str:
    """The first prompt of a plain story session (``config.brief: "plain"``, epic-delivery): the story itself, the
    declared test commands and the brief, like plain Claude Code's prompt (the story file plus three sentences,
    ~2.7K characters). ``""`` for any other phase.

    Without it every story started with "call workflow_run_status first", a 12K
    character contract the session read before any work; the contract stays available for a pipeline failure or review
    findings, which come back as their own short prompts (:func:`_resumed_prompt`)."""
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
    """The prompt of a pass that resumes the phase's own session: short, it names only what changed.

    Starting every pass fresh spent 15-54 calls re-orienting (workflow_run_status
    25 times, SPEC.md 7 times, 189 Reads against 6 in a plain Claude Code session of the same story)."""
    if retry:
        return run_text("resumed_retry", phase=node.title, run_id=run.id)
    import json

    facts = _phase_facts(run, node)
    details = {name: facts[name] for name in CHANGED_FIELDS if facts.get(name)}
    prompt = run_text("resumed", phase=node.title, run_id=run.id, what_changed=_what_changed(run, node))
    if not details:
        return run_text("resumed.ask", resumed=prompt)
    # The changed fields themselves, whole, instead of a status call: otherwise each resumed
    # pass first fetched the whole contract again (18-25K characters, ~7-10K tokens, task list and rules it already
    # had) into a session that was already at 100-160K, so every call of the pass ran above Haiku's 100K price tier.
    return run_text("resumed.details", resumed=prompt, details=json.dumps(details, ensure_ascii=False, indent=1))
