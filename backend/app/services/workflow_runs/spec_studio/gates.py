"""Spec gates: what a spec must say before the product owner may approve it.

In a benchmark, every miss below produced findings the engines then built faithfully — a prompt verb without a default
that works on the first launch, numeric rules without a realistic example, screens
without an empty state or next step, mixed terminology, undefined condition words.
Each miss is an open point in the Studio; approval stays blocked until none is left. Deterministic: no model.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from .design import contrast_report

_DIGIT = re.compile(r"\d")
PRODUCT_OWNER = "product_owner"


def _point(section: str, target: str, text: str) -> dict[str, str]:
    return {"section": section, "target": target, "text": text}


def block_texts(blocks: list[dict[str, Any]]) -> Iterator[str]:
    """Every visible text of a block tree (the copy the glossary checks)."""
    for block in blocks:
        for key in ("text", "title", "meta", "badge", "label", "value", "suffix", "sub", "action", "art"):
            if block.get(key):
                yield str(block[key])
        for item in block.get("items") or []:
            yield from (str(item[k]) for k in ("text", "label", "value") if item.get(k))
        yield from block_texts(list(block.get("blocks") or []))


def _requirements(artefact: dict[str, Any]) -> list[dict[str, str]]:
    points = []
    if not artefact["requirements"] and artefact["mode"] == "new":
        points.append(_point("requirements", "", "List every requirement of the prompt with whether it works with "
                                                 "zero configuration (yes/no) and how."))
    for item in artefact["requirements"]:
        if item.get("zero_config") not in ("yes", "no") or not item.get("how"):
            points.append(_point("requirements", item["id"], f"{item['id']} '{item.get('text', '')}': say whether "
                                 "it works with zero configuration (yes/no) and how (the default it ships)."))
    return points


def _rules(artefact: dict[str, Any], state: dict[str, Any]) -> list[dict[str, str]]:
    points = []
    changed = dict(state.get("rules") or {})
    for rule in artefact["rules"]:
        examples = [e for e in rule["examples"] if e.get("given") and e.get("expect")]
        numeric = rule.get("numeric") or bool(_DIGIT.search(rule.get("text") or ""))
        if not examples:
            points.append(_point("rules", rule["id"], f"{rule['id']} {rule['title']}: add a worked example "
                                                      "(given → expected); it becomes the test."))
        elif numeric and not any(e.get("realistic") for e in examples):
            points.append(_point("rules", rule["id"], f"{rule['id']} {rule['title']}: add one realistic example on "
                                 "real equipment or data (not only boundary values)."))
        if any(dict(changed.get(rule["id"]) or {}).values()):
            points.append(_point("rules", rule["id"], f"{rule['id']}: you changed a value; send the spec to "
                                                      "revision so the worked example is recomputed."))
    return points


def _screens(artefact: dict[str, Any]) -> list[dict[str, str]]:
    points = []
    if artefact["mode"] == "new" and not artefact["flow"].get("progressive_disclosure"):
        points.append(_point("flow", "", "Define the UX flow: what is shown first, what only after the "
                                         "prerequisites exist (progressive disclosure)."))
    for screen in artefact["screens"]:
        name = f"{screen['name']}"
        if not screen["filled"]:
            points.append(_point("screens", screen["id"], f"{name}: the filled state is missing."))
        if not screen["empty"] and not screen.get("empty_not_applicable"):
            points.append(_point("screens", screen["id"], f"{name}: the empty state is missing (or say why there "
                                                          "is none)."))
        if not screen["next_step"]:
            points.append(_point("screens", screen["id"], f"{name}: say what the next step is from here."))
    return points


def _glossary(artefact: dict[str, Any]) -> list[dict[str, str]]:
    if not artefact["glossary"]:
        return [_point("glossary", "", "Add the glossary: every domain word in the app's language with its "
                                       "translation and the words to avoid.")]
    points = []
    for screen in artefact["screens"]:
        copy = " ".join(block_texts([*screen["filled"], *screen["empty"]]))
        for entry in artefact["glossary"]:
            for word in entry["avoid"]:
                if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", copy, re.IGNORECASE):
                    points.append(_point("glossary", screen["id"], f"{screen['name']}: '{word}' is used; the "
                                         f"glossary says '{entry['term']}'."))
    return points


def _conditions(artefact: dict[str, Any]) -> list[dict[str, str]]:
    points = [_point("conditions", c["word"], f"'{c['word']}': define it (field or formula).")
              for c in artefact["conditions"] if not c["definition"]]
    if artefact["rules"] and not artefact["conditions"]:
        points.append(_point("conditions", "", "Define every condition word the rules and screens use (for "
                                               "example ready, overdue, low stock) by field or formula."))
    return points


def _contrast(design: dict[str, Any]) -> list[dict[str, str]]:
    points = [_point("design", f"{row['theme']}:{row['pair']}", f"{row['pair']} ({row['theme']}): {row['ratio']}:1 "
                     "is below WCAG AA 4.5:1.") for row in contrast_report(design) if not row["passes"]]
    if design.get("direction") == "corporate":
        # The company's own colours: only the product owner can deviate from them (with a reason), not the agent.
        points = [{**point, "by": PRODUCT_OWNER} for point in points]
    return points


def _deviations(deviations: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{**_point("design", f"deviation:{d['path']}", f"{d['path']} differs from Corporate ({d['chosen']} "
                      f"instead of {d['corporate']}): give the reason."), "by": PRODUCT_OWNER}
            for d in deviations if not d["reason"].strip()]


def _acceptance(artefact: dict[str, Any], state: dict[str, Any]) -> list[dict[str, str]]:
    points = []
    if not artefact["acceptance"]:
        points.append(_point("acceptance", "", "Add the acceptance criteria every story is measured against."))
    verdicts = dict(state.get("acceptance") or {})
    for item in artefact["acceptance"]:
        if dict(verdicts.get(item["id"]) or {}).get("verdict") == "change":
            points.append(_point("acceptance", item["id"], f"{item['id']} is marked 'change': send the spec to "
                                                           "revision."))
    return points


def open_points(artefact: dict[str, Any], state: dict[str, Any], design: dict[str, Any],
                deviations: list[dict[str, Any]] = ()) -> list[dict[str, str]]:
    """Every open point, in the Studio's section order; empty means the spec may be approved. A point with
    ``by: product_owner`` is the product owner's to settle in the Studio, never sent to the agent."""
    return [*_screens(artefact), *_contrast(design), *_deviations(list(deviations)), *_requirements(artefact),
            *_rules(artefact, state), *_glossary(artefact), *_conditions(artefact), *_acceptance(artefact, state)]


def needs_revision(points: list[dict[str, str]]) -> bool:
    """Only the product owner's own changes are open (changed rule values, rejected criteria): revise, not fix."""
    return bool(points) and all("send the spec to revision" in p["text"] for p in points)


__all__ = ["PRODUCT_OWNER", "block_texts", "needs_revision", "open_points"]
