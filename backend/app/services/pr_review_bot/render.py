"""The bot's review as the pull request shows it: one summary comment, inline comments and a status."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .diff_lines import ADDED, CONTEXT, FileChange, line_kind, old_line_of, range_in_diff
from .render_summary import acceptance, cell, footer, incremental_lines, walkthrough, where
from .suggestion_names import problem
from .suggestion_range import cover

MARKER = "<!-- octryx-review-summary -->"
STATUS_CONTEXT = "octryx/review"
SEVERITY_LABELS = {"high": "🔴 High", "medium": "🟠 Medium", "low": "🔵 Low"}
_ORDER = {"high": 0, "medium": 1, "low": 2}
BLOCKING = frozenset({"high", "medium"})


@dataclass(slots=True)
class InlineComment:
    path: str
    line: int
    body: str
    start_line: int = 0  # 0: a single-line comment
    line_type: str = ADDED  # Bitbucket Server/Data Center's anchor line type
    finding_id: str = ""  # which finding it carries (its thread is answered by a later pass); not sent
    old_line: int = 0  # GitLab: a context line's old-side number (it anchors unchanged lines on both sides)

    def to_dict(self) -> dict[str, Any]:
        record = {"path": self.path, "line": self.line, "body": self.body, "line_type": self.line_type}
        record = {**record, "start_line": self.start_line} if self.start_line else record
        return {**record, "old_line": self.old_line} if self.old_line else record


@dataclass(slots=True)
class ReviewPost:
    summary: str
    comments: list[InlineComment] = field(default_factory=list)
    state: str = "success"  # success | failure
    description: str = ""
    placed: list[tuple[str, str]] = field(default_factory=list)  # (severity, inline | summary) per finding


def _fence(text: str) -> str:
    longest = max((len(run) for run in text.split("\n") for run in _backtick_runs(run)), default=0)
    return "`" * max(3, longest + 1)


def _backtick_runs(line: str) -> list[str]:
    runs, current = [], ""
    for char in line:
        if char == "`":
            current += char
        elif current:
            runs.append(current)
            current = ""
    return [*runs, current] if current else runs


def _comment_body(finding: dict[str, Any], provider: str, above: int = 0, refused: str = "") -> str:
    severity = str(finding.get("severity") or "low")
    head = f"**{SEVERITY_LABELS.get(severity, severity)}**" + (f" · {finding['id']}" if finding.get("id") else "")
    body = f"{head}\n\n{str(finding.get('fix') or '').strip()}"
    suggestion = str(finding.get("suggestion") or "")
    if not suggestion.strip():
        return body
    fence = _fence(suggestion)
    if refused:
        return (f"{body}\n\nSuggested change (apply by hand and complete it: {refused}):\n\n"
                f"{fence}\n{suggestion.rstrip()}\n{fence}")
    if provider == "github":
        return f"{body}\n\n{fence}suggestion\n{suggestion.rstrip()}\n{fence}"
    if provider == "gitlab":
        return f"{body}\n\n{fence}suggestion:-{above}+0\n{suggestion.rstrip()}\n{fence}"
    return f"{body}\n\nSuggested change:\n\n{fence}\n{suggestion.rstrip()}\n{fence}"


def _inline(finding: dict[str, Any], files: dict[str, FileChange], provider: str,
            sources: dict[str, str] | None = None) -> InlineComment | None:
    path, line = str(finding.get("file") or "").strip(), finding.get("line")
    if type(line) is not int or not path:
        return None
    kind = line_kind(files, path, line)
    if not kind:
        return None
    start = finding.get("start_line")
    start = start if type(start) is int and 0 < start < line and range_in_diff(files, path, start, line) else 0
    suggestion = str(finding.get("suggestion") or "")
    if start and not suggestion.strip():
        start = 0  # a range only carries a suggestion that replaces it; a plain finding sits on its line
    if suggestion.strip():
        first, line = cover(files, path, start or line, line, suggestion)  # also the lines it rewrites below
        start = first if first < line else 0
        kind = line_kind(files, path, line)
    source = (sources or {}).get(path.lstrip("./"))
    refused = problem(path, source, start or line, line, suggestion) if suggestion.strip() else ""
    start = 0 if refused else start  # a text block is no range: the comment sits on its line
    old = old_line_of(files, path, line) if provider == "gitlab" and kind == CONTEXT else 0
    return InlineComment(path, line, _comment_body(finding, provider, line - start if start else 0, refused), start,
                         kind, str(finding.get("id") or ""), old)


def _counts(findings: list[dict[str, Any]]) -> str:
    counted = [(severity, sum(1 for item in findings if item.get("severity") == severity)) for severity in _ORDER]
    parts = [f"{count} {severity}" for severity, count in counted if count]
    return " · ".join(parts) if parts else "none"


def build_post(review: dict[str, Any], files: dict[str, FileChange], *, provider: str,
               facts: dict[str, Any]) -> ReviewPost:
    findings = sorted((dict(item) for item in review.get("findings") or [] if isinstance(item, dict)),
                      key=lambda item: (_ORDER.get(str(item.get("severity")), 3), str(item.get("file")),
                                        item.get("line") if type(item.get("line")) is int else 0))
    comments, outside, placed = [], [], []
    carried = [item for item in findings if item.get("carried")]  # open before: their comments are already there
    for finding in findings:
        if finding.get("carried"):
            continue
        comment = _inline(finding, files, provider, facts.get("sources"))
        (comments.append(comment) if comment is not None else outside.append(finding))
        placed.append((str(finding.get("severity") or "low"), "inline" if comment is not None else "summary"))
    # A new finding below high on an incremental pass is shown but does not block (``incremental.effective``).
    blocking = [item for item in findings if item.get("severity") in BLOCKING and not item.get("nonblocking")]
    passed = str(review.get("verdict") or "") == "pass" and not blocking
    title = "looks good" if passed else "changes requested"
    lines = [MARKER, f"## Octryx review: {title}", "", *incremental_lines(facts.get("incremental"), facts)]
    checked = [item for item in findings if item.get("source") == "caller_check"]
    red = [item for item in findings if item.get("source") == "ci"]
    if checked:
        # The deterministic finding first: the reviewer's sentence below may judge only the diff
        # (it could say "behaviour is unchanged" over a broken call outside it).
        lines += [f"**Blocking (deterministic):** {len(checked)} call(s) outside the diff no longer fit a changed "
                  "signature, see the table below.", ""]
    if red:
        lines += [f"**Blocking (CI):** {len(red)} check(s) failed on this commit, see the table below.", ""]
    secrets = [item for item in findings if item.get("source") == "scan" and item.get("kind") == "secrets"]
    if secrets:
        lines += [f"**Blocking (secret scan):** {len(secrets)} committed secret(s); remove and rotate them.", ""]
    checked = checked or red
    if str(review.get("summary") or "").strip():
        label = "Reviewer: " if checked else ""
        lines += [f"> {label}{cell(review['summary'])}", ""]
    lines.append(f"**Findings:** {_counts(findings)}" + (f" ({len(comments)} inline)" if comments else ""))
    if outside:
        lines += ["", "Findings outside the changed lines:", "", "| Severity | Where | Finding |", "|---|---|---|"]
        lines += [f"| {SEVERITY_LABELS.get(str(item.get('severity')), item.get('severity'))} | "
                  f"{where(item)} | {cell(item.get('fix'))} |" for item in outside]
    lines += acceptance(review.get("acceptance"))
    if carried:
        lines += ["", "Still open from earlier passes:", "", "| Severity | Where | Finding |", "|---|---|---|"]
        lines += [f"| {SEVERITY_LABELS.get(str(item.get('severity')), item.get('severity'))} | "
                  f"{where(item)} | {cell(item.get('fix'))} |" for item in carried]
    words = {str(item.get("file")): str(item.get("change")) for item in review.get("walkthrough") or []
             if isinstance(item, dict) and item.get("file") and item.get("change")}
    triage = dict(facts.get("triage") or {})
    reading = {str(item.get("path")): str(item.get("kind")) for item in triage.get("files") or []}
    if triage.get("hotspots"):
        lines += ["", "**Look closely here:**", ""] + [
            f"- `{cell(spot.get('path'))}:{spot.get('line')}`: {cell('; '.join(spot.get('reasons') or []))}"
            for spot in triage["hotspots"]]
    if triage.get("size_note"):
        lines += ["", str(triage["size_note"])]
    lines += ["", *walkthrough(files, words, reading or None), "", footer(facts)]
    state, description = _status(facts, findings, blocking, passed)
    return ReviewPost("\n".join(lines), comments, state, description, placed)


def _status(facts: dict[str, Any], findings: list[dict[str, Any]], blocking: list[dict[str, Any]],
            passed: bool) -> tuple[str, str]:
    secrets = [item for item in findings if item.get("kind") == "secrets"]
    # Every finding is counted, the low ones too ("No blocking findings"
    # without a number would break the promise that findings are counted).
    clean = "No blocking findings" + (f" · {_counts(findings)}" if findings else "")
    if str(facts.get("status_policy") or "inform") == "gate":
        return ("success" if passed else "failure", clean if passed else
                f"{len(blocking)} blocking finding(s): {_counts(findings)}" if blocking else "Changes requested")
    if secrets:
        return "failure", f"{len(secrets)} committed secret(s): remove and rotate"
    return "success", (clean if passed else
                       f"Informational: {len(blocking)} finding(s) to look at: {_counts(findings)}" if blocking
                       else "Informational: changes suggested")


__all__ = ["BLOCKING", "MARKER", "STATUS_CONTEXT", "InlineComment", "ReviewPost", "build_post"]
