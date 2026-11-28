"""The summary comment's parts besides findings (``render``): walkthrough, acceptance criteria, the incremental
pass and the footer. Pure."""

from __future__ import annotations

from typing import Any

from .diff_lines import FileChange


def cell(text: Any) -> str:
    return " ".join(str(text or "").split()).replace("|", "\\|")


_READING = {"careful": "🔎 careful", "skim": "👀 skim", "mechanical": "⚙️ mechanical"}


def walkthrough(files: dict[str, FileChange], words: dict[str, str],
                reading: dict[str, str] | None = None) -> list[str]:
    added, removed = sum(item.added for item in files.values()), sum(item.removed for item in files.values())
    rows = [f"<details><summary>Walkthrough: {len(files)} file(s), +{added} −{removed}</summary>", "",
            "| File | Change | Lines |" + (" Reading |" if reading else ""),
            "|---|---|---|" + ("---|" if reading else "")]
    for path in sorted(files):
        change = files[path]
        what = words.get(path) or (f"renamed from `{change.old_path}`" if change.status == "renamed" else change.status)
        rows.append(f"| `{cell(path)}` | {cell(what)} | +{change.added} −{change.removed} |"
                    + (f" {_READING.get(reading.get(path, ''), '')} |" if reading else ""))
    return [*rows, "", "</details>"]


def where(finding: dict[str, Any]) -> str:
    if finding.get("source") == "ci":
        return "CI"
    return f"`{cell(finding.get('file'))}:{finding.get('line')}`"


_ACCEPTANCE_MARKS = {"covered": "✅ covered", "partial": "🟡 partial", "missing": "❌ missing",
                     "not_assessed": "❔ not assessed"}


def acceptance(rows: Any) -> list[str]:
    rows = [dict(row) for row in rows or [] if isinstance(row, dict) and row.get("criterion")]
    if not rows:
        return []
    table = ["", "**Acceptance criteria:**", "", "| Criterion | Status | Evidence |", "|---|---|---|"]
    return table + [f"| {cell(row.get('criterion'))} | {_ACCEPTANCE_MARKS.get(str(row.get('status')), '')} | "
                    f"{cell(row.get('evidence'))} |" for row in rows]


def incremental_lines(passed: Any, facts: dict[str, Any]) -> list[str]:
    if not isinstance(passed, dict) or not passed.get("from"):
        return []
    fixed, withdrawn = list(passed.get("fixed") or []), list(passed.get("withdrawn") or [])
    line = (f"**Incremental pass** `{str(passed['from'])[:7]}..{str(facts.get('sha') or '')[:7]}`: "
            f"{len(fixed)} fixed, " + (f"{len(withdrawn)} withdrawn, " if withdrawn else "")
            + f"{passed.get('still_open', 0)} still open, {passed.get('new', 0)} new.")
    rows = [f"- ✅ {where(item)} {cell(item.get('fix'))}" for item in fixed]
    taken_back = [f"- ↩️ {where(item)} {cell(item.get('fix'))}" for item in withdrawn]
    return [line, "", *(["Fixed since the last pass:", "", *rows, ""] if rows else []),
            *(["Withdrawn after an answer in the thread:", "", *taken_back, ""] if taken_back else [])]


def footer(facts: dict[str, Any]) -> str:
    parts = [f"Reviewed commit `{str(facts.get('sha') or '')[:12]}`"]
    ticket = dict(facts.get("ticket") or {})
    if ticket.get("key"):
        parts.append(f"ticket {ticket['key']}" + (f" ({cell(ticket.get('title'))[:80]})" if ticket.get("title")
                                                  else ""))
    if facts.get("model"):
        route = f"{facts['seat_of']}'s seat" if facts.get("seat_of") else (
            f"{facts['route']} route" if facts.get("route") else "")
        parts.append(f"reviewer {facts['model']}" + (f" ({route})" if route else ""))
    if facts.get("run_id"):
        parts.append(f"Octryx run `{facts['run_id']}`")
    if facts.get("ci_pending"):
        parts.append(f"CI still running: {', '.join(facts['ci_pending'])}")
    if facts.get("ci_unread"):
        parts.append(f"CI: {facts['ci_unread']}")
    spec = dict(facts.get("spec") or {})
    if spec.get("path") or spec.get("pages"):
        named = [f"`{spec['path']}`"] if spec.get("path") else []
        named += [f"Confluence '{cell(page.get('title'))[:60]}'" for page in spec.get("pages") or []]
        parts.append("spec " + ", ".join(named))
    graph = dict(facts.get("graph") or {})
    if graph.get("callers"):
        parts.append(f"code graph: {graph['callers']} use(s) of {graph.get('symbols')} changed symbol(s) in "
                     f"{graph.get('files')} file(s)")
    if graph.get("callees"):
        parts.append(f"{graph['callees']} called definition(s) shown to the reviewer")
    if spec.get("notes"):
        parts.append("; ".join(str(note) for note in spec["notes"])[:200])
    if facts.get("threads"):
        parts.append(str(facts["threads"]))
    if facts.get("not_checked"):
        parts.append(f"callers not checked for {', '.join(facts['not_checked'])}")
    scan = dict(facts.get("scan") or {})
    if scan.get("tools"):
        parts.append(f"scanned with {', '.join(scan['tools'])}"
                     + (f" ({scan['dropped']} more scan finding(s) not shown)" if scan.get("dropped") else ""))
    if scan.get("notes"):
        parts.append("; ".join(str(note) for note in scan["notes"])[:200])
    if facts.get("authored_by_run"):
        parts.append(f"opened by Octryx run `{facts['authored_by_run']}` (its own review was the first pass)")
    return "<sub>" + " · ".join(parts) + "</sub>"


__all__ = ["acceptance", "cell", "footer", "incremental_lines", "walkthrough", "where"]
