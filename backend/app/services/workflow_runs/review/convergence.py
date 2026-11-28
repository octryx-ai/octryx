"""Reviews that converge: follow-up rounds answer the previous findings, and only real problems in scope count."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .verdict import (
    BLOCKING_SEVERITIES,
    VERDICT_CHANGES,
    VERDICT_PASS,
    Finding,
    Verdict,
    _assumptions,
    finding_from,
)

FIXED, NOT_FIXED, WITHDRAWN, PARTLY = "fixed", "not_fixed", "withdrawn", "partly_fixed"
_FIXED_WORDS = frozenset({"fixed", "resolved", "done", "addressed"})
_IMAGE = re.compile(r"\.(png|jpe?g|webp|gif)$", re.IGNORECASE)
_LINE_SUFFIX = re.compile(r":\d+(-\d+)?$")
_ID = re.compile(r"^F(\d+)$")

FOLLOW_UP_RULE = (
    "This is a follow-up review: the agent worked on your previous findings since. They are listed at the end of "
    "the task, each with its id. Do not audit the whole change again. For every previous finding decide whether "
    "the change now fixes it. Answer with one JSON object only: {\"summary\": \"<one sentence>\", \"previous\": "
    "[{\"id\": \"<F1, ...>\", \"status\": \"fixed\" or \"not_fixed\", \"evidence\": \"<the file:line or the words "
    "in the change that show it>\"}], \"findings\": [{\"severity\": \"high\", \"file\": \"<path>\", \"line\": <line "
    "number>, \"fix\": \"<the concrete change the author must make>\"}]}. Answer every previous id. \"findings\" "
    "lists only new problems of severity \"high\" (other new points are not reported, so the review converges "
    "instead of finding new details each round); never restate a previous finding as a new one. An empty list "
    "when there is no new high problem. A previous finding may carry \"replies\": what people answered in its "
    "thread. When a reply explains why the finding does not apply, answer \"withdrawn\" with the reason in "
    "\"evidence\", unless the change or the code shows new evidence that it does apply: then \"not_fixed\", and "
    "the evidence must name it (never only repeat the finding). When the change fixes only part of a finding, answer "
    "\"partly_fixed\" with what it fixed in \"evidence\" and what is still to do in \"remaining\" (the finding "
    "stays open with only that).")


@dataclass(frozen=True)
class Scope:
    changed: tuple[str, ...] = ()
    screens: tuple[str, ...] = ()
    root: Path | None = None

    def covers(self, file: str) -> bool:
        # Unsure counts as covered.
        path = _LINE_SUFFIX.sub("", str(file or "").strip()).lstrip("./")
        if not self.changed or not path or path.startswith("("):
            return True
        name = path.rsplit("/", 1)[-1]
        if path in self.screens or name in self.screens:
            return True
        if any(item == path or item.endswith(f"/{path}") or path.endswith(f"/{item}") for item in self.changed):
            return True
        if _IMAGE.search(path):
            return False
        if self.root is not None:
            try:
                return not (self.root / path).exists()
            except OSError:
                return True
        return True


@dataclass(frozen=True)
class Settled:
    verdict: Verdict
    dropped: tuple[dict[str, Any], ...] = ()
    answers: tuple[dict[str, Any], ...] = field(default=())

    def record(self) -> dict[str, Any]:
        record = self.verdict.to_dict()
        if self.dropped:
            record["dropped"] = list(self.dropped)
        if self.answers:
            record["follow_up"] = list(self.answers)
        return record


def previous_findings(run: Any, node: Any) -> tuple[Finding, ...]:
    previous = dict(dict(getattr(run, "context", None) or {}).get("review") or {})
    if node is None or previous.get("node_id") != node.id or previous.get("verdict") != VERDICT_CHANGES:
        return ()
    found = []
    for index, raw in enumerate(previous.get("findings") or [], 1):
        finding = finding_from(raw)
        if finding is not None:
            found.append(_with_id(finding, finding.id or f"F{index}"))
    return tuple(found)


def follow_up_task(previous: tuple[Finding, ...]) -> str:
    import json

    rows = [{"id": item.id, "severity": item.severity, "file": item.file, "line": item.line, "fix": item.fix,
             **({"replies": list(item.replies)} if item.replies else {})} for item in previous]
    return ("Your findings of the previous review (the agent worked on them since); answer each id:\n"
            + json.dumps(rows, ensure_ascii=False))


def settle_first(verdict: Verdict, scope: Scope) -> Settled:
    numbered = [_with_id(item, f"F{index}") for index, item in enumerate(verdict.findings, 1)]
    kept, dropped = _in_scope(numbered, scope)
    # The bot's walkthrough rides along (``verdict.WALKTHROUGH_RULE``); a follow-up answer carries none.
    return Settled(replace(_derived(verdict.summary, kept, verdict.assumptions), walkthrough=verdict.walkthrough,
                           acceptance=verdict.acceptance),
                   tuple(dropped))


def settle_follow_up(answer: Any, previous: tuple[Finding, ...], scope: Scope) -> Settled | None:
    if not isinstance(answer, dict):
        return None
    raw_new = answer.get("findings") if answer.get("findings") is not None else []
    raw_previous = answer.get("previous")
    said = str(answer.get("verdict") or "").strip().lower()
    if not isinstance(raw_new, list) or (not isinstance(raw_previous, list) and said not in (VERDICT_PASS,
                                                                                             VERDICT_CHANGES)):
        return None
    new = [finding_from(item) for item in raw_new]
    if any(item is None for item in new):
        return None
    default = NOT_FIXED if isinstance(raw_previous, list) or said == VERDICT_CHANGES else FIXED
    statuses, answers = _statuses(raw_previous if isinstance(raw_previous, list) else [])
    kept: list[Finding] = []
    dropped: list[dict[str, Any]] = []
    for item in previous:
        status = statuses.get(item.id, default)
        if status in (FIXED, WITHDRAWN):
            dropped.append({**item.to_dict(), "dropped": status})
        elif status == PARTLY:
            rest = next(answer["remaining"] for answer in answers if answer["id"] == item.id)
            kept.append(replace(item, fix=rest, suggestion="", start_line=0))
        else:
            kept.append(item)
    known = {(item.file, item.fix) for item in previous}
    number = max([int(match.group(1)) for item in previous if (match := _ID.match(item.id))] or [0])
    for item in new:
        if (item.file, item.fix) in known:
            continue
        if item.severity != "high":
            dropped.append({**item.to_dict(), "dropped": "new_not_high"})
            continue
        number += 1
        kept.append(_with_id(item, f"F{number}"))
    kept, out_of_scope = _in_scope(kept, scope)
    from .verdict import _acceptance

    # The PR review bot re-assesses some acceptance criteria on an incremental pass (``ACCEPTANCE_RULE``); optional,
    # informative, read like a first round's.
    settled = replace(_derived(str(answer.get("summary") or "").strip(), kept, _assumptions(answer.get("assumptions"))),
                      acceptance=_acceptance(answer.get("acceptance")))
    return Settled(settled, tuple(dropped + out_of_scope), tuple(answers))


def _statuses(raw: list[Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    statuses: dict[str, str] = {}
    answers: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("id") or "").strip():
            continue
        ident = str(item["id"]).strip().upper()
        said = str(item.get("status") or "").strip().lower()
        remaining = str(item.get("remaining") or "").strip()
        status = (FIXED if said in _FIXED_WORDS else WITHDRAWN if said == WITHDRAWN
                  else PARTLY if said == PARTLY and remaining else NOT_FIXED)
        statuses[ident] = status
        answers.append({"id": ident, "status": status, "evidence": str(item.get("evidence") or "").strip(),
                        **({"remaining": remaining[:1000]} if status == PARTLY else {})})
    return statuses, answers


def _in_scope(findings: list[Finding], scope: Scope) -> tuple[list[Finding], list[dict[str, Any]]]:
    kept, dropped = [], []
    for item in findings:
        if item.severity == "high" or scope.covers(item.file):
            kept.append(item)
        else:
            dropped.append({**item.to_dict(), "dropped": "out_of_scope"})
    return kept, dropped


def _derived(summary: str, findings: list[Finding], assumptions: tuple[str, ...]) -> Verdict:
    blocking = any(item.severity in BLOCKING_SEVERITIES for item in findings)
    return Verdict(VERDICT_CHANGES if blocking else VERDICT_PASS, summary, tuple(findings), assumptions)


def _with_id(finding: Finding, ident: str) -> Finding:
    return replace(finding, id=ident)


def changed_paths(diff: str) -> tuple[str, ...]:
    paths: list[str] = []
    for match in re.finditer(r"^diff --git a/(\S+) b/(\S+)$", diff or "", re.MULTILINE):
        for path in match.groups():
            if path not in paths:
                paths.append(path)
    return tuple(paths)


__all__ = ["FIXED", "FOLLOW_UP_RULE", "NOT_FIXED", "Scope", "Settled", "changed_paths", "follow_up_task",
           "previous_findings", "settle_first", "settle_follow_up", "PARTLY", "WITHDRAWN"]
