"""``bug.intake_check``: does the bug report say what is needed to reproduce it?

A bug report needs **steps** to reproduce, the **expected** and the **actual** behaviour and the **environment**
(device, browser, version); a screenshot is optional. They are read from the Work item's text as headings or
labelled lines (``Steps:``, ``Expected``, ``Actual``, ``Environment``/``Device``) and kept on the run
(``context.bug_report``).

In a repository with several apps the report also needs the **app** (``workspace.app_choice``); its options go with
the question. Complete: route ``succeeded`` (no question, no person). Missing fields: route ``incomplete`` to the one
question round (the ``intake`` phase asks only for what is missing, with a proposed answer each; the reporter answers
once with buttons) - never a back and forth.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....models.runtime.secure_work import WorkItem
from ..platform.dispatch import ToolOutcome

ROUTE_INCOMPLETE = "incomplete"
FIELDS = {
    "steps": r"steps(?: to reproduce)?|repro(?:duction)? steps",
    "expected": r"expected(?: result| behaviou?r)?",
    "actual": r"actual(?: result| behaviou?r)?|observed(?: behaviou?r)?",
    "environment": r"environment|device|browser|version|platform",
}
OPTIONAL = {"screenshot": r"screenshot|!\[|\.png\b|\.jpe?g\b"}
# A field is a heading (``## Steps``), a bold label (``**Expected:**``) or a label with a colon (``Actual: ...``);
# never a sentence that starts with the word ("Device rotation breaks ...").
_LABEL = (r"^\s*(?:#{1,4}\s*(?:NAMES)\b\s*:?|\*\*(?:NAMES)\s*:?\s*\*\*\s*:?|(?:[-*]\s*)?(?:NAMES)\s*:)"
          r"\s*(.*)$")


def _label(names: str) -> str:
    return _LABEL.replace("NAMES", names)


def fields_of(text: str) -> dict[str, str]:
    """The report's fields: the text under a heading or after a label, up to the next field's."""
    lines = text.splitlines()
    found: dict[str, str] = {}
    current = ""
    for line in lines:
        matched = next((name for name, names in FIELDS.items()
                        if re.match(_label(names), line, re.IGNORECASE)), "")
        if matched:
            current = matched
            rest = re.match(_label(FIELDS[matched]), line, re.IGNORECASE).group(1).strip()
            found[current] = rest
        elif current and line.strip():
            found[current] = f"{found[current]}\n{line.strip()}".strip()
    return {name: value for name, value in found.items() if value.strip()}


def report_state(text: str) -> dict[str, Any]:
    fields = fields_of(text)
    return {"fields": fields, "missing": [name for name in FIELDS if name not in fields],
            "screenshot": bool(re.search(OPTIONAL["screenshot"], text, re.IGNORECASE))}


async def intake_check(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> tuple[ToolOutcome, str]:
    """``(outcome, route)``: ``succeeded`` when the report is complete, else ``incomplete``."""
    del params
    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    text = f"{item.title}\n{item.description or ''}" if item is not None else str(run.title or "")
    state = report_state(text)
    answers = [str(entry.get("text") or "") for entry in dict(run.context or {}).get("po_answers") or []
               if isinstance(entry, dict)]
    from ..workspace.app_choice import FIELD as APP_FIELD
    from ..workspace.app_choice import choose_app

    # A repository with several apps: the run's app, else one question with the options.
    choice = await choose_app(db, run, components=list(getattr(item, "components_json", None) or []),
                              text="\n".join([text, *answers]))
    if choice.get("options"):
        state = {**state, "missing": [*state["missing"], APP_FIELD], "app_options": choice["options"]}
    if answers and state["missing"]:  # the one question round was answered: what it gave counts, no second round
        state = {**state, "answered": True, "missing_after_answers": state["missing"], "missing": []}
    run.context = {**dict(run.context or {}), "bug_report": state}
    from .escaped import record_escape

    await record_escape(db, run, item)  # a bug in work the platform delivered (maintenance metrics)
    if state["missing"]:
        return ToolOutcome("succeeded", {"missing": state["missing"]},
                           "the bug report misses: " + ", ".join(state["missing"])), ROUTE_INCOMPLETE
    return ToolOutcome("succeeded", {"fields": sorted(state["fields"])}), "succeeded"


__all__ = ["FIELDS", "ROUTE_INCOMPLETE", "fields_of", "intake_check", "report_state"]
