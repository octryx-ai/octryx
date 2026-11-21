"""The run's test history: per-test results from chat, octryx-claude and CI.

Every test run a governed turn, the octryx gateway or CI reports is appended to ``context.tests.runs`` (the newest
20 are kept). When the confirmed tests are seen red by their role — every new test failing on an assertion, every
regression test passing (``test_roles``) — the run remembers it (``red_seen``): "green" then means red first, then
green. A gate reads this history (``gate_fields``), never the agent's word.

**Content snapshot**: when a person confirms the tests, the content hash of each confirmed test's file
is recorded (``context.confirmed_test_files``, resolved in the run's working copy). Every gate re-reads the files: a
confirmed test whose file changed, disappeared or names no file cannot count as intact or green — rewriting the
reproduction (``assert True``) after red never turns the run green. Phases with ``protect_confirmed_tests`` also
refuse writes to these files (``path_rules``) unless they are formatting only (``format_only``): the snapshot also
keeps the confirmed Python file's syntax-tree fingerprint (``ast_sha256``), so a reformatted file stays intact.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from ...models import WorkflowRun
from ...time_utils import utc_now
from ..workflow_checks.test_ids import file_of, normalize
from ..workflow_checks.test_results import all_red
from .format_only import file_ast_fingerprint
from .test_resolution import recorded_runs, resolve_entry, resolver_for
from .test_roles import ROLE_NEW

MAX_RUNS = 20
ROLES_CONTEXT_KEY = "confirmed_test_roles"


def _tests(run: WorkflowRun) -> dict[str, Any]:
    return dict(dict(run.context or {}).get("tests") or {})


def confirmed_tests(run: WorkflowRun) -> list[str]:
    return [str(item) for item in dict(run.context or {}).get("confirmed_tests") or [] if str(item).strip()]


def confirmed_by(run: Any) -> str:
    """Who bound the confirmed tests (``confirm_tests`` records it): ``person`` or ``run``; ``person`` before any
    confirmation."""
    return str(dict(getattr(run, "context", None) or {}).get(CONFIRMED_BY_KEY) or "person")


def confirmed_test_roles(run: WorkflowRun) -> dict[str, str]:
    """Each confirmed test's role (``test_roles``, recorded by ``confirm_tests``); empty before a confirmation."""
    return {str(key): str(value) for key, value in dict(dict(run.context or {}).get(ROLES_CONTEXT_KEY) or {}).items()}


def record_test_run(run: WorkflowRun, test_run: dict[str, Any], *, node_id: str | None = None) -> None:
    """Append a test run, its results keyed by canonical id as far as the run's files resolve them."""
    tests = _tests(run)
    entry = resolve_entry({**test_run, "node_id": node_id, "at": utc_now().isoformat()}, resolver_for(run))
    tests["runs"] = [*(tests.get("runs") or []), entry][-MAX_RUNS:]
    confirmed = confirmed_tests(run)
    if confirmed and all_red(entry, confirmed, confirmed_test_roles(run))[0]:
        tests["red_seen"] = True
    run.context = {**dict(run.context or {}), "tests": tests}


# A merged phase's confirmed tests: their red is the pipeline's run on the base commit (``size_class.merge``).
RED_ON_BASE_PENDING = "red_on_base_pending"


def gate_fields(run: WorkflowRun) -> dict[str, Any]:
    tests = _tests(run)
    context = dict(run.context or {})
    return {
        "test_runs": recorded_runs(run),
        "confirmed_tests": confirmed_tests(run),
        "confirmed_test_roles": confirmed_test_roles(run),
        "red_on_base": context.get("red_on_base") if isinstance(context.get("red_on_base"), dict) else None,
        "red_seen": bool(tests.get("red_seen") or tests.get(RED_ON_BASE_PENDING)),
        "ci_state": ci_state_of_head(context),
        "symptom": context.get("reproduction_symptom"),
        "confirmed_test_drift": confirmed_test_drift(run),
        "slices": _slice_board(run),
        "definition_of_ready": context.get("definition_of_ready"),
    }


def _slice_board(run: WorkflowRun) -> list[dict[str, Any]] | None:
    slices = dict(dict(run.context or {}).get("slices") or {})
    return [{"key": key, "status": dict(item).get("status")} for key, item in slices.items()] if slices else None


def ci_state_of_head(context: dict[str, Any]) -> str | None:
    """The recorded CI state, only when it is the result for the commit the run pushed last."""
    ci = dict(context.get("ci") or {})
    head = str(context.get("head_sha") or "")
    if head and str(ci.get("sha") or "") != head:
        return None
    return ci.get("state")


CONFIRMED_BY_KEY = "confirmed_tests_by"


def confirm_tests(run: WorkflowRun, test_ids: list[str], *, symptom: str | None = None,
                  roles: dict[str, str] | None = None, by: str = "person") -> None:
    """A confirmed test contract or reproduction names the tests the gates judge from now on, with their roles;
    ``by``: a ``person`` confirmed them, or the ``run`` bound its own reproduction (a size class that skips the
    confirmation)."""
    context = dict(run.context or {})
    context[CONFIRMED_BY_KEY] = by
    context["confirmed_tests"] = list(dict.fromkeys(normalize(item) for item in test_ids if normalize(item)))
    roles = {normalize(key): value for key, value in (roles or {}).items()}
    context[ROLES_CONTEXT_KEY] = {item: str(roles.get(item) or ROLE_NEW) for item in context["confirmed_tests"]}
    if symptom:
        context["reproduction_symptom"] = symptom
    tests = dict(context.get("tests") or {})
    tests.pop(RED_ON_BASE_PENDING, None)  # a confirmation of its own judges its red again
    run.context = context
    runs = recorded_runs(run)
    # The run that showed them is the red evidence when it already has them failing on an assertion.
    tests["red_seen"] = bool(runs) and all_red(runs[-1], context["confirmed_tests"], context[ROLES_CONTEXT_KEY])[0]
    context["tests"] = tests
    run.context = context


def test_file_of(test_id: str) -> str | None:
    """The file a canonical test id names, else ``None`` (``test_ids.file_of``)."""
    return file_of(normalize(test_id))


def _digest(path: Path) -> str | None:
    try:
        return "sha256:" + sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


async def working_copy_root(db: Any, run: WorkflowRun) -> Path | None:
    """Where the run's tests run: its repository working copy, else its chat session's workspace."""
    local_path = str(dict(run.context or {}).get("local_path") or "")
    if local_path:
        return Path(local_path).resolve()
    from ...models import Session
    from ..session.workspace import resolve_session_workspace_root
    from .records import main_session_id

    session_id = await main_session_id(db, run)
    session = await db.get(Session, session_id) if session_id else None
    return Path(str(await resolve_session_workspace_root(db, session))).resolve() if session is not None else None


async def device_run(db: Any, run: WorkflowRun) -> bool:
    from sqlalchemy import select

    from ...models import WorkflowRunSession
    from .octryx.attach import RUNTIME_OCTRYX

    return (await db.execute(select(WorkflowRunSession.id).where(
        WorkflowRunSession.run_id == run.id, WorkflowRunSession.runtime == RUNTIME_OCTRYX,
        WorkflowRunSession.active.is_(True)).limit(1))).first() is not None


async def snapshot_confirmed_tests(db: Any, run: WorkflowRun) -> None:
    """Record the content hash of every confirmed test's file at the moment a person confirmed it.

    A run an octryx-claude session works on has its working copy on the device: the files are marked ``device``
    and the launcher's first report is their baseline (``octryx/facts``)."""
    if await device_run(db, run):
        run.context = {**dict(run.context or {}), "confirmed_test_files": {
            test_id: {"file": test_file_of(test_id), "path": None, "sha256": None, "device": True}
            for test_id in confirmed_tests(run)}}
        return
    root = await working_copy_root(db, run)
    files: dict[str, dict[str, Any]] = {}
    for test_id in confirmed_tests(run):
        relative = test_file_of(test_id)
        path = (root / relative).resolve() if root is not None and relative else None
        if path is not None and root is not None and not path.is_relative_to(root):
            path = None  # a test id never points outside the working copy
        files[test_id] = {"file": relative, "path": str(path) if path else None,
                          "sha256": _digest(path) if path else None,
                          "ast_sha256": file_ast_fingerprint(path) if path else None}
    run.context = {**dict(run.context or {}), "confirmed_test_files": files}


def confirmed_test_drift(run: WorkflowRun) -> list[str]:
    """Why a confirmed test's content can no longer be trusted (empty: unchanged since its confirmation)."""
    confirmed = confirmed_tests(run)
    if not confirmed:
        return []
    files = dict(dict(run.context or {}).get("confirmed_test_files") or {})
    reasons = []
    for test_id in confirmed:
        entry = dict(files.get(test_id) or {})
        if not entry:
            reasons.append(f"{test_id}: no content snapshot from its confirmation")
        elif entry.get("device"):
            if not entry.get("file"):
                reasons.append(f"{test_id}: no test file to verify (the confirmed id must name its file)")
            elif not entry.get("device_sha256"):
                reasons.append(f"{test_id}: the device has not reported its file {entry['file']} yet")
            elif entry.get("device_latest") == "missing":
                reasons.append(f"{test_id}: its file {entry['file']} was removed on the device after it was confirmed")
            elif entry.get("device_latest") != entry["device_sha256"] and not (
                    entry.get("device_program") and entry.get("device_program_latest") == entry["device_program"]):
                # A layout-only change is the same program (the edit guard's own fingerprint, ``format_only``).
                reasons.append(f"{test_id}: its file {entry['file']} changed on the device after it was confirmed")
        elif not entry.get("path") or not entry.get("sha256"):
            reasons.append(f"{test_id}: no test file to verify (the confirmed id must name its file)")
        elif _digest(Path(entry["path"])) != entry["sha256"] and not (
                entry.get("ast_sha256") and file_ast_fingerprint(Path(entry["path"])) == entry["ast_sha256"]):
            reasons.append(f"{test_id}: its file {entry['file']} changed or was removed after it was confirmed")
    return reasons


def confirmed_baseline_intact(run: WorkflowRun, path: Path) -> bool:
    """Whether the current content of the confirmed test file ``path`` is provably the confirmed one: its bytes
    match the confirmed hash, or its syntax tree matches the fingerprint taken at confirmation. Unprovable is
    ``False``."""
    entries = [dict(entry or {}) for entry in dict(dict(run.context or {}).get("confirmed_test_files") or {}).values()
               if isinstance(entry, dict) and entry.get("path") and Path(entry["path"]).resolve() == path.resolve()]
    return bool(entries) and all(
        (entry.get("sha256") and _digest(path) == entry["sha256"])
        or (entry.get("ast_sha256") and file_ast_fingerprint(path) == entry["ast_sha256"]) for entry in entries)


async def record_turn_test_runs(db: Any, run: WorkflowRun, test_runs: list[dict[str, Any]], *,
                                node_id: str | None) -> None:
    """A phase turn's test runs; when the confirmed tests are first seen red, their content is fixed then.

    Tests written after the contract was confirmed (Feature delivery's tests-first phase) exist only from here on:
    their snapshot is taken at the first red run, so no later change can make them pass instead of the code."""
    before = bool(_tests(run).get("red_seen"))
    for test_run in test_runs:
        record_test_run(run, test_run, node_id=node_id)
    if not before and _tests(run).get("red_seen"):
        await snapshot_confirmed_tests(db, run)
    elif test_runs and _last_run_red(run) and await _tests_first_phase(db, run, node_id):
        # The tests-first phase may still correct its tests (the Red loop): the snapshot follows the latest red
        # state there, and is frozen once the run has left that phase (implementation can never rewrite them).
        await snapshot_confirmed_tests(db, run)


def _last_run_red(run: WorkflowRun) -> bool:
    runs = _tests(run).get("runs") or []
    confirmed = confirmed_tests(run)
    return bool(runs and confirmed) and all_red(runs[-1], confirmed, confirmed_test_roles(run))[0]


async def _tests_first_phase(db: Any, run: WorkflowRun, node_id: str | None) -> bool:
    """Whether ``node_id`` is the phase a ``tests_red`` gate judges (its ``phase``, else its direct source)."""
    from .graph import NODE_GATE, graph_for_run

    if not node_id:
        return False
    graph = await graph_for_run(db, run)
    for gate in graph.nodes.values():
        if gate.kind != NODE_GATE or not any(isinstance(check, dict) and check.get("type") == "tests_red"
                                             for check in gate.config.get("checks") or []):
            continue
        phase = gate.config.get("phase")
        if phase == node_id or (not phase and any(edge.source == node_id and edge.target == gate.id
                                                  for edge in graph.edges)):
            return True
    return False


__all__ = ["RED_ON_BASE_PENDING", "ROLES_CONTEXT_KEY", "confirm_tests", "confirmed_test_drift", "confirmed_test_roles",
           "device_run",
           "confirmed_tests", "gate_fields",
           "confirmed_baseline_intact",
           "record_test_run", "record_turn_test_runs", "snapshot_confirmed_tests",
           "test_file_of", "working_copy_root"]
