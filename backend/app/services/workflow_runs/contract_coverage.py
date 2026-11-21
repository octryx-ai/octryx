"""A TDD run's test contract must specify the new behaviour.

Without this check a Clarify agent could submit a test contract of only existing tests, every one ``regression``
and none ``new``: ``phase_outputs._test_contract`` accepted it, the Clarify check passed, and the confirmation card
showed a contract under which "Tests first" had nothing that must fail and the run would have delivered nothing.

When the run's own graph says it is test-first — a gate checks ``tests_red`` (the contract's new tests must fail before
the change) — a submitted test contract is checked against these limits:

1. **At least one ``new`` test, and a ``new`` test is proven new** (:func:`new_test_refusals`).
   ``new`` is a concrete test case — ``file::test_x`` or ``file::Class::test_x`` — the run's base does not define
   (read from the run's working copy at its base commit; Python resolved with ``ast``), or a whole file the base tree
   provably does not have. An existing file, class or test, a folder, or any form that cannot be proven is refused —
   relabelling an existing test never passes the gate. Absence counts only from a successful tree lookup; a git
   error, timeout or unreadable blob refuses ``needs_configuration`` and records nothing.
2. **Only real Work-item criteria need a new test.** The structured source is the confirmed Definition of Ready of the
   item's triage run (Workflow A, ``context.definition_of_ready.acceptance_criteria``), addressed ``AC1``…``ACn`` in
   that order: each needs a contract criterion with that id and at least one ``new`` test (or ``manual_only`` with its
   reason). Further criteria the agent adds (regressions) may stay regression-only. A free-text description is never
   parsed into criteria.
3. **The source is named, coverage is not claimed.** Every refusal names where the criteria came from; the recorded
   contract carries ``criteria_source`` — the source, or that the item has none, and that whether the tests prove
   the ticket stays the person's check. Nothing here judges semantic coverage from counts or labels.
4. **An automatic refusal is no decision.** It is a failed submit: nothing is recorded or replaced (the existing
   contract stays as it was), no confirmation, no human rejection, no loop is consumed; the phase's ``tool_called``
   check fails, the agent gets the checks reminder and submits again.

The person's confirmation stays its own gate; nothing here writes tests. Regression tests stay allowed, ``manual_only``
is unaffected, and a run whose graph has no ``tests_red`` gate (any other output, any other workflow) is unaffected.

A test contract for a typed accepted-spec child instead consumes the exact parent criteria, stable IDs and
Given/When/Then through the public current-receiver authority resolver. This strict path precedes the graph's
``tests_red`` guard: an unavailable spec never falls back to DoR or free text. It requires genuine new tests/manual
reasons but does not add a Red gate or claim semantic coverage. The eventual engineering graph owns its real Red gate.
"""

from __future__ import annotations

import ast
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkflowRun
from ..workflow_checks.test_ids import file_of
from .graph import NODE_GATE, graph_for_run
from .records import WorkflowRunError
from .test_roles import ROLE_NEW, ROLES_KEY

TESTS_RED_CHECK = "tests_red"
CRITERIA_SOURCE_KEY = "criteria_source"
INVALID_OUTPUT, NEEDS_CONFIGURATION = "invalid_output", "needs_configuration"


def _checks(config: dict[str, Any]) -> list[dict[str, Any]]:
    contract = config.get("workflow_contract") if isinstance(config.get("workflow_contract"), dict) else {}
    raw = [*(config.get("checks") or []), *(contract.get("checks") or [])]
    return [item for item in raw if isinstance(item, dict)]


def graph_requires_new_tests(graph: Any) -> bool:
    """True when the graph has a gate that needs the contract's new tests failing first (``tests_red``)."""
    return any(node.kind == NODE_GATE and any(check.get("type") == TESTS_RED_CHECK for check in _checks(node.config))
               for node in graph.nodes.values())


async def requires_new_tests(db: AsyncSession, run: WorkflowRun) -> bool:
    return graph_requires_new_tests(await graph_for_run(db, run))


async def structured_criteria(db: AsyncSession, run: WorkflowRun) -> tuple[list[str], str]:
    """``(criteria, source)``: the Work item's acceptance criteria from its confirmed Definition of Ready (triage
    outcome ``done``) and that run's id, else ``([], '')``."""
    from .definition_of_ready import DOR_KEY, TRIAGE_WORKFLOW_KEY

    if not run.work_item_id:
        return [], ""
    rows = (await db.execute(select(WorkflowRun.id, WorkflowRun.context).where(
        WorkflowRun.work_item_id == run.work_item_id, WorkflowRun.workflow_key == TRIAGE_WORKFLOW_KEY,
        WorkflowRun.status == "completed", WorkflowRun.outcome == "done",
    ).order_by(WorkflowRun.completed_at.desc()).limit(1))).all()
    if not rows:
        return [], ""
    record = dict(dict(rows[0].context or {}).get(DOR_KEY) or {})
    criteria = [str(item).strip() for item in record.get("acceptance_criteria") or [] if str(item or "").strip()]
    return criteria, (f"the Work item's confirmed Definition of Ready (triage run {rows[0].id})" if criteria else "")


def _new_tests(criterion: dict[str, Any]) -> list[str]:
    roles = dict(criterion.get(ROLES_KEY) or {})
    return [str(test) for test in criterion.get("tests") or [] if roles.get(str(test)) == ROLE_NEW]


_COPY_UNREADABLE = ("the run's working copy at its base commit could not be read, so it cannot be proven that the "
                    "'new' tests do not exist yet; re-prepare the run's working copy, then submit again")


def _is_test_name(name: str) -> bool:
    """A name pytest collects as a test case (``test*`` functions and methods)."""
    return name.startswith("test")


def _python_scope(content: str, chain: list[str]) -> tuple[str, str] | None:
    """What ``file::A::B::name`` resolves to at the base: ``(kind, '')`` with kind ``function`` | ``class`` |
    ``absent``, or ``None`` when the file does not parse (unprovable)."""
    try:
        body: list[ast.stmt] = ast.parse(content).body
    except SyntaxError:
        return None
    *outer, name = chain
    for part in outer:
        scope = next((node for node in body if isinstance(node, ast.ClassDef) and node.name == part), None)
        if scope is None:
            return "absent", ""  # the enclosing class is new: so is everything in it
        body = scope.body
    for node in body:
        if getattr(node, "name", None) == name:
            return ("class" if isinstance(node, ast.ClassDef) else "function"), ""
    return "absent", ""


async def new_test_refusals(run: WorkflowRun, test_ids: list[str]) -> tuple[list[str], str]:
    """``(refusals, '')`` for the selectors marked ``new`` that are not proven new test cases at the run's base, or
    ``([], why)`` when the base could not be read (``needs_configuration``; nothing is assumed).

    Allowed as ``new``: a concrete test case — ``file::test_x`` or ``file::Class::test_x`` (any nesting) — that the
    base does not define, in a file that exists or not; or a whole file the base tree provably does not have. Refused:
    a file, class or folder that exists, a test the base defines, and any form that cannot be proven (a directory, a
    name without its file, a name pytest does not collect, a file that does not parse). Absence counts only from a
    successful tree lookup (``git ls-tree <base> -- <path>`` answering nothing); any git error, timeout or unreadable
    blob is ``needs_configuration``.
    """
    from . import safe_git
    from .phase_workspace import run_working_copy

    root = run_working_copy(run)
    base = str(dict(run.context or {}).get("base_sha") or "")
    if root is None or not base or (await safe_git.git(root, "cat-file", "-e", f"{base}^{{commit}}"))[0] != 0:
        return [], _COPY_UNREADABLE
    present: dict[str, bool] = {}
    contents: dict[str, str] = {}
    refusals: list[str] = []
    for test_id in test_ids:
        file = file_of(test_id)
        chain = [part.split("[", 1)[0] for part in test_id.split("::")[1:]]
        if file is None or any(not part for part in chain):
            refusals.append(f"{test_id}: a 'new' test is a concrete test case (file::test or file::Class::test) or a "
                            "new file; this selector cannot be proven new")
            continue
        if file not in present:
            code, out, _err = await safe_git.git(root, "ls-tree", base, "--", file)
            if code != 0:
                return [], _COPY_UNREADABLE
            present[file] = bool(out.strip())
        if not present[file]:
            continue  # a file the base tree does not have: the file and every test in it are new
        if not chain:
            refusals.append(f"{test_id}: the file already exists at the run's base; name the new test cases in it "
                            "(file::test) — an existing file is not a new test")
            continue
        if file not in contents:
            code, out, _err = await safe_git.git(root, "show", f"{base}:{file}")
            if code != 0:
                return [], _COPY_UNREADABLE
            contents[file] = out
        if file.endswith(".py"):
            resolved = _python_scope(contents[file], chain)
            kind = resolved[0] if resolved is not None else None
        else:
            kind = "function" if re.search(rf"\b{re.escape(chain[-1])}\b", contents[file]) else "absent"
        if kind is None:
            refusals.append(f"{test_id}: {file} does not parse at the run's base; the selector cannot be proven new")
        elif kind == "class":
            refusals.append(f"{test_id}: the class already exists at the run's base; name its new test methods "
                            "(file::Class::test) — an existing class is not a new test")
        elif kind == "function":
            refusals.append(f"{test_id}: is marked 'new' but already exists at the run's base; an existing test is "
                            "'regression' — a 'new' test is one the branch does not have yet")
        elif not _is_test_name(chain[-1]):
            refusals.append(f"{test_id}: '{chain[-1]}' is not a test case name the runner collects (test…); name the "
                            "concrete new test")
    return refusals, ""


async def check_contract_coverage(
    db: AsyncSession, run: WorkflowRun, record: dict[str, Any], *, principal: User | None = None
) -> tuple[dict[str, Any], list[str], str]:
    """``(record, problems, reason)`` for a submitted contract (roles resolved): unchanged and ``[]`` outside a
    test-first run unless spec-bound. A claimed spec requires actual-principal authority before the graph guard;
    ``needs_configuration`` refuses unavailable authority or an unreadable base without replacing a contract."""
    from .specification.engineering_contract import accepted_spec_criteria, criterion_text

    try:
        spec_source = await accepted_spec_criteria(db, run, principal=principal)
    except WorkflowRunError:
        return (record, ["The accepted specification or current receiver/source authority could not be verified."],
                NEEDS_CONFIGURATION)
    if spec_source is None and not await requires_new_tests(db, run):
        return record, [], ""
    criteria = [dict(item) for item in record.get("criteria") or [] if isinstance(item, dict)]
    if spec_source is not None:
        source = spec_source["source"]
        expected = [(item["id"], criterion_text(item)) for item in spec_source["criteria"]]
        record = {**record, CRITERIA_SOURCE_KEY: spec_source}
    else:
        work_item_criteria, source = await structured_criteria(db, run)
        expected = [(f"AC{index}", text) for index, text in enumerate(work_item_criteria, start=1)]
        record = {**record, CRITERIA_SOURCE_KEY: {
            "source": source or None, "work_item_criteria": len(work_item_criteria),
            "note": ("each Work-item criterion ACk has at least one new test or an explicit manual reason; whether "
                     "those tests prove the criterion "
                     "stays the person's check" if source else
                     "the Work item carries no structured acceptance criteria (only a description): matching the tests "
                     "to the ticket stays the person's check"),
        }}
    problems: list[str] = []
    new_ids = list(dict.fromkeys(test for item in criteria for test in _new_tests(item)))
    if not new_ids:
        problems.append("tests: an accepted-spec test contract needs at least one genuine 'new' test; "
                        "existing tests may stay as 'regression' on top." if spec_source is not None else
                        "tests: this run is test-first (its red gate needs new tests failing before the change), "
                        "but every test is 'regression'. Name at least one 'new' test that specifies the Work item's "
                        "behaviour; existing tests may stay as 'regression' on top.")
    else:
        refusals, why = await new_test_refusals(run, new_ids)
        if why:
            return record, [why], NEEDS_CONFIGURATION
        problems += refusals
    by_id = {(str(item.get("id") or "").strip() if spec_source is not None else
              str(item.get("id") or "").strip().upper()): item for item in criteria}
    for key, text in expected:
        criterion = by_id.get(key)
        manual = criterion is not None and (
            bool(criterion.get("manual_only")) if spec_source is None else
            criterion.get("manual_only") is True and bool(str(criterion.get("manual_reason") or "").strip()))
        if criterion is not None and (manual or _new_tests(criterion)):
            continue
        problems.append(f"{key}: {source} lists \"{text[:200]}\"; it needs a contract criterion with id {key} and at "
                        "least one 'new' test (or manual_only with its reason). Further criteria of your own may "
                        "stay regression-only.")
    return record, problems, INVALID_OUTPUT if problems else ""


__all__ = ["CRITERIA_SOURCE_KEY", "NEEDS_CONFIGURATION", "TESTS_RED_CHECK", "check_contract_coverage",
           "new_test_refusals", "graph_requires_new_tests", "requires_new_tests", "structured_criteria"]
