"""Where the Studio meets the run's flow: the decisions confirmation, the auto-accept and the push.

- A person confirms the spec's ``decisions`` gate (Studio or decision card): refused while open points are left,
  else frozen and written back as their approval.
- The platform would auto-accept: open points the agent can fix go back to it first, as a product owner answer,
  within the node's automatic revisions (the same budget as the review's findings).
- The push: a run confirmed without a person (auto-accept after the revisions) still freezes and writes back, so
  SPEC.md always carries the decisions the stories build on; the frozen version keeps the open points it had.
"""

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
    """The open points the agent fixes itself (not the product owner's own changes, which go through revision)."""
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
    """What the agent hears after ``submit_spec_studio``: the open points it fixes before it ends its phase (never
    the product owner's own: deviation reasons, the company's colours), and the Corporate Identity it starts from."""
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
