"""Phase outputs: a phase proposes a structured artefact, the server records it on the run.

A phase that must hand something on declares it in its definition: ``{"type": "phase", "config": {"output":
"<kind>", ...}}``. Its agent ends by calling the kind's submit tool (chat tool and run-bound MCP tool, same
handler semantics): the server validates the proposal and records it under the run (``context.outputs[kind]``,
versioned, with its hash, node and pass). The agent needs no write rights anywhere: whatever the artefact becomes
outside the run (a Work change plan, a Jira text) is a server step that reads the recorded output
(``platform/work_plan``, ``platform/texts``). A phase may also declare ``inputs`` — recorded outputs its agent
reads in its contract (chat contract line, octryx run contract).

Kinds (closed):

- ``definition_of_ready`` (Workflow A triage, ``submit_definition_of_ready``): recorded also when incomplete; the
  ``definition_of_ready`` check decides (``workflow_runs/definition_of_ready``).
- ``test_contract`` (B clarify, ``submit_test_contract``): criteria → tests (each ``new`` or ``regression``,
  ``test_roles``: derived and checked against the run's recorded test runs) → command, or a manual-only criterion
  with its reason; ``work.draft_change_plan`` turns it into the Work item's change plan.
- ``reproduction`` (C reproduce, ``submit_reproduction``): the tests that reproduce the bug and the symptom; the
  reproduction confirmation shows it next to the tests the server saw failing.
- ``incident_hypothesis`` (E hypothesis, ``submit_incident_hypothesis``): cause, impact, next step, whether a code
  fix is needed, the cited sources; the bug ticket's text and the hand-over to C.
- ``feature_documentation`` (B documentation, ``submit_feature_documentation``): title, what, why, how to use; the
  page adds the recorded acceptance criteria → tests and links (``documentation``).
- ``story_plan`` (the epic's split, ``submit_story_plan``): the stories in build order (``teamwork.stories``);
  ``work.create_stories`` creates them under the epic.
- ``spec_studio`` (spec-writing draft, ``submit_spec_studio``): the structured spec next to SPEC.md the product
  owner reviews and approves in the Spec Studio (``spec_studio``); the answer lists the open points left.
- ``work_plan`` (the coordinator, ``submit_work_plan``): the shared contract and the items a following
  ``parallel_work`` node runs (``teamwork.plan``); recording it stores the run's task list (one task per item). The
  coordinator may also submit a revised plan while the items run (at the ``parallel_work`` node, from any session
  but an item's).

A phase that declares ``result_values`` also records its **result**: its agent ends with
``submit_phase_result`` naming one of them (``{"value", "summary"?}``, refused outside the declared values). The
phase is done only once it recorded one in its current pass; a following decision routes on it (``conditions``).

An invalid proposal is refused with its problems (a refusal is a failed tool call, so it never counts for a
``tool_called`` check); the Definition of Ready keeps its own rule (recorded with what is missing).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from ...models import WorkflowRun
from ...time_utils import utc_now
from .conditions import phase_result_values
from .graph import NODE_PARALLEL, NODE_PHASE, PhasedNode
from .specification.integration import KINDS as SPECIFICATION_KINDS
from .specification.integration import proposal_validator

OUTPUTS_KEY = "outputs"
HANDOFF_KEY = "handoff"
MAX_ITEMS = 30
MAX_TEXT = 1000


def _text(value: Any, limit: int = MAX_TEXT) -> str:
    return str(value or "").strip()[:limit]


def _texts(value: Any, limit: int = 500) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item, limit) for item in value if _text(item)][:MAX_ITEMS]


def _test_contract(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    problems: list[str] = []
    criteria: list[dict[str, Any]] = []
    items = raw.get("criteria") if isinstance(raw.get("criteria"), list) else []
    for index, entry in enumerate(items[:MAX_ITEMS], start=1):
        entry = entry if isinstance(entry, dict) else {}
        criterion = {"id": _text(entry.get("id"), 40) or f"AC{index}", "text": _text(entry.get("text"))}
        if not criterion["text"]:
            problems.append(f"criteria[{index}]: text is empty")
        if entry.get("manual_only") is True:
            criterion.update(manual_only=True, manual_reason=_text(entry.get("manual_reason")))
            if not criterion["manual_reason"]:
                problems.append(f"{criterion['id']}: a manual-only criterion names why no test can prove it")
        else:
            from .test_roles import ROLES_KEY, parse_tests

            tests, roles, role_problems = parse_tests(entry.get("tests"), limit=MAX_ITEMS)
            criterion.update(tests=tests, command=_text(entry.get("command"), 500), **{ROLES_KEY: roles})
            problems += [f"{criterion['id']}: {problem}" for problem in role_problems]
            if not criterion["tests"] or not criterion["command"]:
                problems.append(f"{criterion['id']}: name its tests and the command that runs them "
                                "(or mark it manual_only with a reason)")
        criteria.append(criterion)
    if not criteria:
        problems.append("criteria: at least one acceptance criterion")
    ids = [item["id"] for item in criteria]
    if len(set(ids)) != len(ids):
        problems.append("criteria: every criterion needs its own id")
    if criteria and all(item.get("manual_only") for item in criteria):
        problems.append("criteria: at least one criterion is proven by a test")
    record = {"summary": _text(raw.get("summary")), "criteria": criteria,
              "open_questions": _texts(raw.get("open_questions"))}
    return record, problems


def _reproduction(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    record = {"tests": _texts(raw.get("tests"), 300), "symptom": _text(raw.get("symptom")),
              "steps": _texts(raw.get("steps")), "explanation": _text(raw.get("explanation"), 2000)}
    problems = [message for field, message in (
        ("tests", "tests: the test ids that reproduce the bug (as the test run reports them)"),
        ("symptom", "symptom: the failure the tests show, in the reported terms"),
    ) if not record[field]]
    return record, problems


def _incident_hypothesis(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    needed = raw.get("code_fix_needed")
    record = {"summary": _text(raw.get("summary"), 240), "cause": _text(raw.get("cause"), 2000),
              "impact": _text(raw.get("impact")), "next_step": _text(raw.get("next_step")),
              "code_fix_needed": needed if isinstance(needed, bool) else None, "sources": _texts(raw.get("sources"))}
    problems = [f"{field}: missing" for field in ("summary", "cause", "impact", "next_step") if not record[field]]
    if record["code_fix_needed"] is None:
        problems.append("code_fix_needed: true or false")
    if not record["sources"]:
        problems.append("sources: cite the evidence the hypothesis rests on")
    return record, problems


def _definition_of_ready(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    from .definition_of_ready import validate_record

    return validate_record(raw), []  # recorded even when incomplete: the definition_of_ready check decides


def _work_plan(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    from .teamwork.plan import validate_plan

    return validate_plan(raw)  # the roles are checked against the parallel_work node in ``submit_output``


def _story_plan(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    from .teamwork.stories import validate_story_plan

    return validate_story_plan(raw)


def _spec_studio(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    from .spec_studio.schema import validate_spec_studio

    return validate_spec_studio(raw)


def _feature_documentation(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    from .documentation.record import validate_feature_documentation

    return validate_feature_documentation(raw)


@dataclass(frozen=True, slots=True)
class OutputSpec:
    kind: str
    tool: str
    title: str
    validate: Callable[[dict[str, Any]], tuple[dict[str, Any], list[str]]]


OUTPUT_SPECS: dict[str, OutputSpec] = {spec.kind: spec for spec in (
    OutputSpec("definition_of_ready", "submit_definition_of_ready", "Definition of Ready", _definition_of_ready),
    OutputSpec("test_contract", "submit_test_contract", "Test contract", _test_contract),
    OutputSpec("reproduction", "submit_reproduction", "Reproduction", _reproduction),
    OutputSpec("incident_hypothesis", "submit_incident_hypothesis", "Incident hypothesis", _incident_hypothesis),
    OutputSpec("feature_documentation", "submit_feature_documentation", "Feature documentation",
               _feature_documentation),
    OutputSpec("work_plan", "submit_work_plan", "Work plan", _work_plan),
    OutputSpec("story_plan", "submit_story_plan", "Story plan", _story_plan),
    OutputSpec("spec_studio", "submit_spec_studio", "Spec Studio", _spec_studio),
)}
OUTPUT_SPECS.update({kind: OutputSpec(kind, f"submit_{kind}", kind.replace("_", " ").title(),
                                    proposal_validator(kind)) for kind in sorted(SPECIFICATION_KINDS)})


def _phase_result(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    record = {"value": _text(raw.get("value"), 80), "summary": _text(raw.get("summary"))}
    return record, ([] if record["value"] else ["value: one of the phase's possible results"])


# A phase's result: declared by ``result_values``, never an ``output`` kind of its own.
RESULT_KIND = "result"
RESULT_TOOL = "submit_phase_result"
RESULT_SPEC = OutputSpec(RESULT_KIND, RESULT_TOOL, "Result", _phase_result)
OUTPUT_BY_TOOL = {spec.tool: spec for spec in (*OUTPUT_SPECS.values(), RESULT_SPEC)}


def output_hash(record: dict[str, Any]) -> str:
    return "sha256:" + sha256(json.dumps(record, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def phase_output(node: PhasedNode | None) -> str:
    return _text((node.config if node is not None else {}).get("output"), 80)


def phase_inputs(node: PhasedNode) -> list[str]:
    return [str(item) for item in node.config.get("inputs") or [] if str(item or "").strip()] if isinstance(
        node.config.get("inputs"), list) else []


def phase_accepts(node: PhasedNode | None, spec: OutputSpec) -> bool:
    """The phase submits this output: it declares it, or (a version before output contracts) offers its tool."""
    if node is None or node.kind != NODE_PHASE:
        return False
    if spec.kind == RESULT_KIND:
        return bool(phase_result_values(node))
    if phase_output(node) == spec.kind:
        return True
    policy = node.config.get("tool_policy") if isinstance(node.config.get("tool_policy"), dict) else {}
    return spec.tool in (policy.get("allowlist") or []) and spec.tool not in (policy.get("denylist") or [])


def phase_result(run: WorkflowRun, node: PhasedNode) -> str | None:
    """The result the phase's agent recorded in the run's current pass of ``node`` (one of its result_values)."""
    envelope = recorded_output(run, RESULT_KIND) or {}
    value = _text(dict(envelope.get("record") or {}).get("value"), 80)
    if (envelope.get("node_id") != node.id or envelope.get("entry") != dict(run.node_state or {}).get("entry")
            or value not in phase_result_values(node)):
        return None
    return value


def recorded_output(run: WorkflowRun, kind: str) -> dict[str, Any] | None:
    """The newest recorded output of ``kind`` on the run (its envelope), else ``None``."""
    envelope = dict(dict(run.context or {}).get(OUTPUTS_KEY) or {}).get(kind)
    return dict(envelope) if isinstance(envelope, dict) else None


def available_inputs(run: WorkflowRun, kinds: list[str]) -> dict[str, Any]:
    """What a phase reads: its declared inputs recorded on this run, and whatever a parent run handed over."""
    inputs = {kind: envelope["record"] for kind in kinds if kind not in SPECIFICATION_KINDS
              if (envelope := recorded_output(run, kind)) and isinstance(envelope.get("record"), dict)}
    handoff = dict(dict(run.context or {}).get(HANDOFF_KEY) or {})
    return {**{kind: dict(value) for kind, value in handoff.items()
               if isinstance(value, dict) and kind not in SPECIFICATION_KINDS}, **inputs}


def _canonical_tests(run: WorkflowRun, record: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    """``record`` with its test ids canonical, the problems of ids that cannot be, and every id it names."""
    from .test_resolution import canonical_ids, resolver_for
    from .test_roles import ROLES_KEY

    raw = [str(test) for criterion in record.get("criteria") or [] for test in criterion.get("tests") or []]
    raw += [str(test) for test in record.get("tests") or []]
    resolver = resolver_for(run, raw)
    problems: list[str] = []

    def canonical(ids: list[str]) -> list[str]:
        mapped, refused = canonical_ids(ids, resolver)
        problems.extend(refused)
        return mapped

    if "criteria" in record:
        criteria = []
        for criterion in record["criteria"]:
            criterion = dict(criterion)
            if not criterion.get("manual_only"):
                renamed = {item: (resolver.selector(item)[0] or item) for item in criterion.get("tests") or []}
                criterion["tests"] = canonical(list(criterion.get("tests") or []))
                criterion[ROLES_KEY] = {renamed.get(key, key): value
                                        for key, value in dict(criterion.get(ROLES_KEY) or {}).items()}
            criteria.append(criterion)
        record = {**record, "criteria": criteria}
    if "tests" in record:
        record = {**record, "tests": canonical(list(record.get("tests") or []))}
    ids = [str(test) for criterion in record.get("criteria") or [] for test in criterion.get("tests") or []]
    return record, list(dict.fromkeys(problems)), ids + list(record.get("tests") or [])


async def submit_output(db: Any, run: WorkflowRun, tool: str, raw: Any, *, principal=None,
                        session_id=None, request_id=None, tool_history=None) -> dict[str, Any]:
    """Validate and record a phase's proposal on the (claimed) run: ``recorded`` with version and hash, or
    ``refused`` with the reason (``outside_phase_output`` / ``invalid_output`` with its problems)."""
    from .graph import graph_for_run
    from .handoff.lifecycle import guard_receiver

    await guard_receiver(db, run)
    spec = OUTPUT_BY_TOOL.get(tool)
    if spec is None:
        return {"state": "refused", "reason": "unknown_output"}
    if run.status != "running":
        return {"state": "refused", "reason": "not_a_run_phase", "message": "The run is not at a phase."}
    graph = await graph_for_run(db, run)
    node = graph.nodes.get(run.current_node_id or "")
    if node is not None and node.kind == NODE_PARALLEL:
        from .teamwork.outputs import parallel_submission

        # At a parallel_work node: an item records its result on its item; the coordinator may revise the plan.
        handled, node = await parallel_submission(db, run, graph, node, spec, raw, session_id=session_id)
        if handled is not None:
            return handled
    if not phase_accepts(node, spec):
        return {"state": "refused", "reason": "outside_phase_output",
                "message": f"The run's current phase does not submit a {spec.title}."}
    record, problems = spec.validate(raw if isinstance(raw, dict) else {})
    if spec.kind == "work_plan" and not problems:
        from .teamwork.outputs import plan_problems

        problems = plan_problems(run, graph, node, record)
    if spec.kind == RESULT_KIND and not problems and record["value"] not in phase_result_values(node):
        problems = [f"value: one of {', '.join(phase_result_values(node))}"]
    reason = ""
    if spec.kind in SPECIFICATION_KINDS and not problems:
        from .specification.integration import actual_principal
        from .specification.lineage import SpecificationUnavailable, canonicalize_output, take_output_provenance

        try:
            record = await canonicalize_output(
                db, run, spec.kind, record, principal=await actual_principal(db, run, principal),
                session_id=session_id, request_id=request_id, tool_history=tool_history)
            provenance = take_output_provenance(db, run, spec.kind, record,
                                                session_id=session_id, request_id=request_id)
        except SpecificationUnavailable as error:
            return {"state": "refused", "reason": error.code,
                    "message": "The specification inputs or current source bindings could not be verified."}
    if spec.kind in ("test_contract", "reproduction") and not problems:
        from .test_resolution import recorded_runs

        # Every test id canonical (``test_ids``) before it is stored, compared or confirmed.
        record, problems, ids = _canonical_tests(run, record)
        if spec.kind == "test_contract" and not problems:
            from .test_roles import resolve_contract

            # Each test's role, derived or checked against what the recorded runs showed on the branch.
            record, problems = resolve_contract(record, recorded_runs(run, ids))
            if not problems:
                from .contract_coverage import check_contract_coverage

                # A test-first run's contract specifies the new behaviour: new tests the base does not have, one per
                # structured Work-item criterion; the record names where the criteria came from.
                # The actual caller only (never the requester): a spec-bound contract fails closed without one.
                record, problems, reason = await check_contract_coverage(db, run, record, principal=principal)
    if problems:
        # A refused proposal is a failed tool call: no record, no human decision, no loop consumed.
        return {"state": "refused", "reason": reason or "invalid_output", "message": "; ".join(problems[:10]),
                "problems": problems[:20]}
    previous = recorded_output(run, spec.kind) or {}
    envelope = {"kind": spec.kind, "version": int(previous.get("version") or 0) + 1, "hash": output_hash(record),
                "node_id": node.id, "entry": dict(run.node_state or {}).get("entry"), "at": utc_now().isoformat(),
                "record": record}
    context = dict(run.context or {})
    context[OUTPUTS_KEY] = {**dict(context.get(OUTPUTS_KEY) or {}), spec.kind: envelope}
    if spec.kind == "definition_of_ready":
        from .definition_of_ready import apply_record

        apply_record(run, context, record)
    run.context = context
    if spec.kind == "research_brief":
        from .specification.lineage import record_output_provenance

        await record_output_provenance(db, run, spec.kind, proof=provenance)
    from .records import record_event

    record_event(db, run, "phase_output_recorded", node_id=node.id,
                 detail={"kind": spec.kind, "version": envelope["version"], "hash": envelope["hash"]})
    from .size_class.merge import output_recorded

    await output_recorded(db, run, graph, node)  # a merged phase: the skipped steps' duties now (``merge``)
    if spec.kind == "work_plan":
        from .teamwork.plan_updates import plan_recorded

        await plan_recorded(db, run, record, session_id=session_id)
    answer: dict[str, Any] = {"state": "recorded", "kind": spec.kind, "version": envelope["version"],
                              "hash": envelope["hash"]}
    if spec.kind == "definition_of_ready":
        answer.update(complete=record["complete"], missing=record["missing"])
    if spec.kind == "spec_studio":
        from .spec_studio.hooks import submit_answer

        answer.update(await submit_answer(db, run))
    return answer


__all__ = [
    "HANDOFF_KEY",
    "OUTPUTS_KEY",
    "OUTPUT_BY_TOOL",
    "OUTPUT_SPECS",
    "OutputSpec",
    "RESULT_KIND",
    "RESULT_TOOL",
    "available_inputs",
    "output_hash",
    "phase_accepts",
    "phase_inputs",
    "phase_output",
    "phase_result",
    "recorded_output",
    "submit_output",
]
