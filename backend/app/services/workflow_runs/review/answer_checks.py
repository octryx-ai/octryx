"""The platform's checks on the reviewer's answer: settling it, the root cause and look floors, the retry rule."""

from __future__ import annotations

import re
from typing import Any

from ....models import WorkflowRun
from .convergence import settle_first, settle_follow_up
from .verdict import parse_verdict


def _reviewed_phase_protects_tests(graph: Any, run: WorkflowRun, config: dict[str, Any]) -> bool:
    from ..path_rules import protects_confirmed_tests

    phase_id = str(config.get("phase") or dict(run.context or {}).get("last_phase") or "")
    phase = graph.nodes.get(phase_id) if phase_id else None
    return phase is not None and protects_confirmed_tests(dict(getattr(phase, "config", None) or {}))


_ROOT_CAUSE = re.compile(r"root cause:\s*\S+:\d+", re.IGNORECASE)


def root_cause_gate(settled: Any) -> Any:
    # Low, because medium would turn a passed verdict into changes.
    import dataclasses

    from .verdict import Finding

    verdict = settled.verdict
    if _ROOT_CAUSE.search(verdict.summary or "") or any("root cause" in item.fix.lower() for item in verdict.findings):
        return settled
    asked = Finding("low", "(work item)", 1, "The review names no root cause: state 'Root cause: <file>:<line>' "
                    "and whether the fix removes it.", "RC1")
    return dataclasses.replace(settled, verdict=dataclasses.replace(verdict, findings=(*verdict.findings, asked)))


def _settle(answer: Any, previous: tuple[Any, ...], scope: Any) -> Any:
    if previous:
        return settle_follow_up(answer, previous, scope)
    verdict = parse_verdict(answer)
    return settle_first(verdict, scope) if verdict is not None else None


_LOOK_CHECK = re.compile(r"\bLF\s*-?\s*(\d+)\b", re.IGNORECASE)


def look_floor(answer: Any, notes: list[Any]) -> Any:
    # The verdict call sees only the screenshot notes, so a missed look must not vanish between the two calls.
    if not isinstance(answer, dict) or not isinstance(answer.get("findings", []), list):
        return answer
    findings = list(answer.get("findings") or [])
    said = " ".join([str(answer.get("summary") or "")] + [
        f"{item.get('file') or ''} {item.get('fix') or ''}" for item in findings if isinstance(item, dict)]).lower()
    added = []
    for note in notes:
        if not isinstance(note, dict) or str(note.get("severity") or "").strip().lower() != "high":
            continue
        check = _LOOK_CHECK.search(str(note.get("check") or ""))
        shot = str(note.get("screenshot") or "").strip()
        if check is None or not shot:
            continue
        label = f"LF{check.group(1)}"
        if shot.lower() in said or re.search(rf"\blf\s*-?\s*{check.group(1)}\b", said):
            continue
        added.append({"severity": "high", "file": shot, "line": 1,
                      "fix": f"{label}, {shot}: {str(note.get('problem') or '').strip()}"})
    if not added:
        return answer
    return {**answer, "verdict": "changes", "findings": findings + added}


RETRY_RULE = ("Your previous answer was not one valid JSON verdict object. Answer again with exactly one JSON object "
              "in the format given above and nothing else: no prose, no code fence. Keep it short: one sentence per "
              "finding, the most important first.")
