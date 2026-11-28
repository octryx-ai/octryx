"""Where the Studio meets the run's flow: the decisions confirmation, the auto-accept and the push."""

from __future__ import annotations

from typing import Any

from .corporate_link import refresh
from .gates import PRODUCT_OWNER
from .service import evaluate, freeze

OPEN_POINTS_ANSWER = ("The Spec Studio lists open points the product owner cannot approve with. Fix each in SPEC.md "
                      "and submit_spec_studio again:\n")


async def on_decisions_confirmed(db: Any, run: Any, user: Any) -> None:
    from ..records import WorkflowRunError

    await refresh(db, run)
    view = evaluate(run)
    if view is None or view["frozen"]:
        return
    if view["open_points"]:
        count = len(view["open_points"])
        raise WorkflowRunError("spec_open_points", f"The Spec Studio has {count} open point{'s' if count != 1 else ''}"
                                                   f": {view['open_points'][0]['text']}", 409)
    await freeze(db, run, user=user, how="product_owner")


def agent_open_points(run: Any) -> list[dict[str, str]]:
    view = evaluate(run)
    if view is None or view["frozen"]:
        return []
    return [p for p in view["open_points"]
            if "send the spec to revision" not in p["text"] and p.get("by") != PRODUCT_OWNER]


def note_open_points(run: Any, points: list[dict[str, str]]) -> None:
    from ....time_utils import utc_now

    text = OPEN_POINTS_ANSWER + "\n".join(f"- {p['text']}" for p in points)
    answers = [*list(dict(run.context or {}).get("po_answers") or []),
               {"text": text, "by": None, "at": utc_now().isoformat(), "spec_studio_open_points": len(points)}]
    run.context = {**dict(run.context or {}), "po_answers": answers}


async def submit_answer(db: Any, run: Any) -> dict[str, Any]:
    await refresh(db, run)
    view = evaluate(run) or {}
    answer: dict[str, Any] = {"open_points": [p["text"] for p in view.get("open_points") or []
                                              if p.get("by") != PRODUCT_OWNER]}
    corporate = view.get("corporate")
    if corporate:
        answer["corporate"] = (
            f"The Workspace's Corporate Identity \"{corporate['profile_name']}\" is the preselected look in the "
            "Studio: the product owner sees it first and your design directions as alternatives. Use its colours and "
            "fonts; propose another direction only where the product needs it, and say why in its hint.")
    return answer


async def before_push(db: Any, run: Any) -> None:
    await refresh(db, run)
    await freeze(db, run, user=None, how="auto_accepted")


__all__ = ["agent_open_points", "before_push", "note_open_points", "on_decisions_confirmed", "submit_answer"]
