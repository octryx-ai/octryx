"""What a user confirmation decides on: its typed payload, rebuilt from recorded artefacts."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ..workflow_checks.test_ids import normalize
from .graph import PhasedNode, graph_for_run
from .phase_outputs import output_hash, recorded_output
from .test_resolution import recorded_runs
from .test_roles import ROLE_NEW, contract_roles, role_conflicts

# a real PO interview (a 7327-character answer) fits easily; anything beyond
# this guard is marked on the card, never dropped without a word.
MAX_PAYLOAD_TEXT = 20_000
_CLOSED_PLAN = ("approved", "rejected", "superseded")


def _last_answer(run: WorkflowRun, phase_id: str) -> str:
    answers = dict(dict(run.context or {}).get("answers") or {})
    context = dict(run.context or {})
    return capped(str(answers.get(phase_id or str(context.get("last_phase") or "")) or ""), MAX_PAYLOAD_TEXT)


def capped(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n\n(truncated, {len(text) - limit:,} more characters)"


def plan_hash(plan: Any) -> str:
    return output_hash({"id": plan.id, "version": plan.version,
                        "acceptance_criteria": list(plan.acceptance_criteria_json or []),
                        "validation_plan": list(plan.validation_plan_json or []),
                        "open_questions": list(plan.open_questions_json or [])})


async def _missing_producer(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> bool:
    from .data_flow import missing_producers

    return bool(missing_producers(await graph_for_run(db, run), node))


async def _test_contract(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> dict[str, Any]:
    from ...models.runtime.secure_work import WorkChangePlan
    from ..secure_work.plans.acceptance_coverage import acceptance_coverage_blockers

    if not run.work_item_id:
        return {"missing": "The run has no Work item, so there is no change plan to confirm."}
    drafted = dict(dict(run.context or {}).get("change_plan") or {})
    if drafted:
        plan = await db.get(WorkChangePlan, str(drafted.get("id") or ""))
        if plan is None or plan.status in _CLOSED_PLAN:
            return {"missing": f"The change plan v{drafted.get('version')} drafted from the test contract is "
                               f"{plan.status if plan is not None else 'gone'} now; change the tests to draft it "
                               "again."}
    else:
        plan = (await db.execute(
            select(WorkChangePlan).where(WorkChangePlan.work_item_id == run.work_item_id,
                                         WorkChangePlan.status.not_in(_CLOSED_PLAN))
            .order_by(WorkChangePlan.version.desc()).limit(1)
        )).scalar_one_or_none()
        if plan is None and await _missing_producer(db, run, node):
            return {"missing": "This workflow version has no step that drafts the change plan from the test "
                               "contract (fixed in the current version). Create the plan in Work, or stop this run "
                               "and start it again on the current version.", "design_gap": True}
        if plan is None:
            return {"missing": "The Work item has no open change plan yet."}
    criteria = list(plan.acceptance_criteria_json or [])
    validation = list(plan.validation_plan_json or [])
    manual = [str(item.get("id")) for item in criteria if isinstance(item, dict) and item.get("manual_only")]
    test_ids = contract_test_ids({"acceptance_criteria": criteria})
    roles = contract_roles(criteria, test_ids)
    runs = recorded_runs(run, test_ids)
    return {
        "change_plan_id": plan.id, "version": plan.version, "plan_hash": plan_hash(plan),
        "acceptance_criteria": criteria, "validation_plan": validation, "manual_only": manual,
        "open_questions": list(plan.open_questions_json or []), "test_roles": roles,
        "blockers": acceptance_coverage_blockers(
            plan_type=str(dict(plan.evidence_json or {}).get("plan_type") or ""), criteria=criteria,
            validation_plan=validation, has_change_units=bool(plan.change_units_json), human_verified_ids=manual,
        ) + role_conflicts(roles, runs),
    }


def _failing_tests(run: WorkflowRun) -> list[dict[str, str]]:
    runs = recorded_runs(run)
    results = dict(runs[-1].get("results") or {}) if runs else {}
    return [{"id": test_id, "message": str(value.get("message") or "")}
            for test_id, value in sorted(results.items()) if value.get("outcome") == "failed"][:50]


async def _reproduction(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> dict[str, Any]:
    failing = _failing_tests(run)
    payload: dict[str, Any] = {"failing_tests": failing}
    envelope = recorded_output(run, "reproduction")
    if envelope is not None:
        record = dict(envelope.get("record") or {})
        payload.update(tests=list(record.get("tests") or []), symptom=record.get("symptom") or "",
                       steps=list(record.get("steps") or []), explanation=record.get("explanation") or "",
                       output_version=envelope.get("version"))
        not_failing = [test for test in payload["tests"]
                       if not any(same_test(str(item["id"]), test) for item in failing)]
        if not_failing:
            payload["missing"] = ("The submitted reproduction tests do not fail in the last test run: "
                                  f"{', '.join(not_failing[:10])}.")
    elif await _missing_producer(db, run, node):
        payload["text"] = _last_answer(run, str(node.config.get("payload_from") or ""))
    else:
        payload["missing"] = "No reproduction was submitted yet."
    if not failing:
        payload["missing"] = "The last test run shows no test failing on an assertion yet."
    return payload


def _shown(run: WorkflowRun, kind: str) -> dict[str, Any] | None:
    if kind == "review_verdict":
        review = dict(dict(run.context or {}).get("review") or {})
        return {key: review.get(key) for key in ("verdict", "summary", "findings", "assumptions", "at")
                if key != "assumptions" or review.get(key)} if review else None
    envelope = recorded_output(run, kind)
    return {"version": envelope.get("version"), "hash": envelope.get("hash"),
            **dict(envelope.get("record") or {})} if envelope else None


def _latest_gate_state(run: WorkflowRun) -> dict[str, Any]:
    results = [item for item in dict(run.gate_results or {}).values() if isinstance(item, dict)]
    latest = max(results, key=lambda item: str(item.get("at") or ""), default={})
    return {"state": latest.get("state"), "phase": latest.get("phase")}


async def documentation_contract(db: AsyncSession, run: WorkflowRun) -> dict[str, Any]:
    from ..project.service import get_project_config
    from .documentation.page import documentation_settings
    from .documentation.preflight import audience_settings

    config = await get_project_config(run.project_id, db)
    settings, audience = documentation_settings(config), audience_settings(config)
    return {
        "space_key": settings.space_key if settings else None,
        "parent_page_id": (settings.parent_page_id or None) if settings else None,
        "audience": audience.to_dict() if audience else None, "doc_owner": run.requested_by,
        "sections": ["what", "why", "how_to_use", "acceptance criteria and tests", "links"],
        "timing": ("after the merge and before any deploy; published with 'acceptance pending' when the functional "
                   "acceptance is not testable yet"),
        "not_configured": [name for name, value in (("documentation space", settings), ("audience", audience))
                           if value is None],
    }


async def _s1_payload(db: AsyncSession, run: WorkflowRun, subject: str) -> dict[str, Any]:
    from .documentation import acceptance, followup_exception, publication_card

    builders = {"functional_acceptance": acceptance.acceptance_payload,
                "publication": publication_card.publication_payload,
                "followup": followup_exception.followup_payload, "exception": followup_exception.exception_payload}
    return await builders[subject](db, run)


async def _subject_payload(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> dict[str, Any]:
    subject = str(node.config.get("subject") or "")
    if subject == "test_contract":
        payload = {"subject": subject, **await _test_contract(db, run, node)}
        if node.config.get("documentation_contract") is True:
            payload["documentation_contract"] = await documentation_contract(db, run)
        return payload
    if subject in ("functional_acceptance", "publication", "followup", "exception"):
        return await _s1_payload(db, run, subject)
    if subject == "reproduction":
        return {"subject": subject, **await _reproduction(db, run, node)}
    if subject == "questions":
        missing = [str(item) for item in dict(dict(run.context or {}).get("definition_of_ready") or {}).get(
            "missing") or []]
        payload = {"subject": subject, "questions": missing}
        return payload if missing else {**payload, "missing": "Triage recorded no open question."}
    if subject == "advance":
        return {"subject": subject, "ticket_key": run.ticket_key, "branch": run.branch,
                "pull_request": dict(run.pull_request or {}), "gate": _latest_gate_state(run)}
    return {"subject": subject, "text": _last_answer(run, str(node.config.get("payload_from") or ""))}


async def confirmation_payload(db: AsyncSession, run: WorkflowRun, node: PhasedNode, *, principal=None,
                               purpose="preview") -> dict[str, Any]:
    payload = await _subject_payload(db, run, node)
    shows = str(node.config.get("shows") or "").strip()
    from .specification.integration import KINDS, shown_payload

    if shows in KINDS:
        shown = await shown_payload(db, run, kind=shows, principal=principal, purpose=purpose)
        merged = {**payload, "shows": shows, **shown}
        if "blockers" in payload and "blockers" in shown:
            # A subject's own blockers (a test contract's coverage) and the shown record's are both kept.
            merged["blockers"] = [*payload["blockers"], *shown["blockers"]]
        return merged
    if shows:
        shown = _shown(run, shows)
        payload.update(shows=shows, output=shown)
        if shown is None and not payload.get("missing"):
            payload["missing"] = f"No {shows.replace('_', ' ')} was recorded in this run yet."
    if dict(dict(run.context or {}).get("alert") or {}).get("test"):
        payload["test_alert"] = True
    return payload


_TEST_FILE = re.compile(r"(^|/)(test_[^/\s]+|[^/\s]+_test|[^/\s]+Test[s]?|[^/\s]+\.test)\.(py|go|java|kt|ts|js)$")


def contract_test_ids(payload: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for criterion in payload.get("acceptance_criteria") or []:
        if not isinstance(criterion, dict):
            continue
        named = [normalize(item) for item in criterion.get("tests") or [] if normalize(item)]
        if named:
            ids += named
            continue
        for command in criterion.get("validation_commands") or []:
            ids += [normalize(token) for token in str(command).split()
                    if "::" in token or _TEST_FILE.search(token)]
    return list(dict.fromkeys(ids))


def contract_test_roles(payload: dict[str, Any]) -> dict[str, str]:
    ids = contract_test_ids(payload)
    shown = {str(key): str(value) for key, value in dict(payload.get("test_roles") or {}).items()}
    planned = contract_roles(payload.get("acceptance_criteria") or [], ids)
    return {test_id: shown.get(test_id) or planned[test_id] for test_id in ids}


def reproduction_roles(tests: list[str]) -> dict[str, str]:
    return {test_id: ROLE_NEW for test_id in tests}


def same_test(ran: str, named: str) -> bool:
    # The agent may name a test from the repository root while the runner, run in the app folder, reports it shorter.
    from ..workflow_checks.unittest_blocks import path_form

    # unittest's dotted id and pytest's path id name the same test.
    ran, named = path_form(ran), path_form(named)
    return ran == named or ran.endswith("/" + named) or named.endswith("/" + ran)


def reproduction_tests(payload: dict[str, Any]) -> tuple[list[str], str | None]:
    failing = [item for item in payload.get("failing_tests") or [] if isinstance(item, dict)]
    submitted = [str(item) for item in payload.get("tests") or []]
    chosen = [item for item in failing if any(same_test(str(item.get("id")), test) for test in submitted)] \
        if submitted else failing
    symptom = next((str(item.get("message") or "") for item in chosen if item.get("message")), "")
    return [str(item.get("id")) for item in chosen], symptom or None


__all__ = ["MAX_PAYLOAD_TEXT", "capped", "confirmation_payload", "contract_test_ids", "contract_test_roles",
           "plan_hash",
           "reproduction_roles", "reproduction_tests", "same_test"]
