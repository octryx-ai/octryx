"""The base-commit proof of a size class's ``red_on_base`` before anything is pushed.

A merged reproduce+fix turn binds the tests it submits (``size_class.merge.confirm_in_turn``); their red is this
proof alone. So it may never go missing on the way to the pull request: the pipeline stays red with a delta for the
agent when there is nothing to run on the base (:func:`missing`), the pull request names the result for its reader
(:func:`evidence_text`), and it is not opened without a proven verdict (:func:`unproven`).
"""

from __future__ import annotations

from typing import Any

from ...models import WorkflowRun
from .red_on_base import CLASS_KEY, CONTEXT_KEY, FAILED


def _asked(run: WorkflowRun) -> bool:
    from .size_class import class_config

    return class_config(run).get(CLASS_KEY) is True


def missing(run: WorkflowRun, requested: dict[str, Any] | None) -> list[str]:
    """The pipeline's error when the class asks for the proof but no test could be asked for."""
    if not _asked(run) or requested:
        return []
    return ["no reproduction test could run on the base commit: submit the reproduction (submit_reproduction) with "
            "the tests that fail because of the bug; without that proof nothing is pushed"]


def unproven(run: WorkflowRun) -> str:
    """Why the pull request waits: the class asks for the proof and the last verdict is not ``proven``."""
    if not _asked(run):
        return ""
    verdict = dict(dict(run.context or {}).get(CONTEXT_KEY) or {})
    if verdict.get("state") == "proven":
        return ""
    return ("the reproduction is not proven on the base commit "
            f"({verdict.get('state') or 'not run'}{': ' + str(verdict['reason']) if verdict.get('reason') else ''})")


def evidence_text(run: WorkflowRun) -> str:
    """The pull request's section on the proof: each confirmed test failed on the base and passes with the change."""
    verdict = dict(dict(run.context or {}).get(CONTEXT_KEY) or {})
    if not _asked(run) or verdict.get("state") != "proven":
        return ""
    base = str(verdict.get("base") or "")[:10]
    lines = [f"- `{test}`: {'failed' if outcome == FAILED else outcome} on the base commit `{base}`, passes with this "
             "change" for test, outcome in dict(verdict.get("tests") or {}).items()]
    return "## Reproduction proven on the base commit\n\n" + "\n".join(lines) if lines else ""


async def pause_unattributed(db: Any, run: WorkflowRun, tests: list[str], *, why: str = "") -> None:
    """Pause once, cause platform (``evidence_unresolved``), for confirmed tests the base run showed no result for;
    the pipeline step re-runs on continue. ``why``: the base run started no test at all (its command and output end),
    said as such instead of only "could not attribute"."""
    from .limits import pause_run
    from .states import PAUSE_EVIDENCE_UNRESOLVED

    found = (f"The base commit's run of the confirmed tests ({', '.join(tests[:5])}) did not run them: {why}. "
             "This is the platform's command for the base run, not the agent's change; nothing was counted against "
             "the agent. Next: report it to the platform team, or abort; continue runs the pipeline step again."
             if why else
             "The platform could not attribute the base commit's results of these confirmed tests: "
             f"{', '.join(tests[:5])}. Nothing was counted against the agent. Next: continue to run the "
             "pipeline step again, or abort.")
    await pause_run(db, run, reason=PAUSE_EVIDENCE_UNRESOLVED, actor_id=None, detail={
        "code": "red_on_base_unattributed", "tests": tests[:10], **({"started_no_test": True} if why else {}),
        "message": found,
        "resume": {"kind": "restart", "node_id": run.current_node_id}})


__all__ = ["evidence_text", "missing", "pause_unattributed", "unproven"]
