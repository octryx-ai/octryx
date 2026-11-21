"""The pull request's ticket for the reviewer.

``pr_review.prepare`` links the run to a Work item (``run.work_item_id``), so the review's evidence carries its
title, description and acceptance criteria and the specification decisions check finds its keys
(``review.evidence``, ``review.spec_commit``). The key is looked for, in this order, in:

1. the source branch (``feature/-totals``), 2. the pull request's title, 3. its commits' messages (newest first,
   the ``Octryx-Run: <key>`` trailer included).

A key counts only when it names something of this Workspace, so ``UTF-8`` or ``ISO-27001`` never do:

- a Work item the Workspace already has (a platform item, or a ticket its Jira sync stored): linked as it is;
- else a key of a Jira project the Workspace is connected to (its Jira intakes and Jira knowledge sources): the issue
  is read through the governed ``get_jira_ticket`` and stored like the Jira sync stores it (``jira_work_item``).

No key, or a ticket that cannot be read: the review runs; the footer says which ticket it had.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun, WorkItem
from ..workflow_runs import safe_git

logger = logging.getLogger(__name__)
KEY = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]{1,14}-[1-9][0-9]{0,6})(?![0-9])")
MAX_COMMITS = 50


def candidates(branch: str, title: str, messages: list[str]) -> list[str]:
    """Every key-shaped word, upper-cased, in the order the module docstring names; each once. Pure."""
    found: list[str] = []
    for text in [branch, title, *messages]:
        for match in KEY.finditer(str(text or "")):
            key = match.group(1).upper()
            if key not in found:
                found.append(key)
    return found


_AC_LABEL = re.compile(r"^\s*(?:[-*•]\s*)?\**(A[CK])\s*-?\s*(\d{1,2})\**\s*[:.)\-–]\s*(.+)$", re.IGNORECASE)
_AC_HEADING = re.compile(r"^\s*(?:#+\s*|\*\*)?(acceptance criteria|akzeptanzkriterien|definition of done)\b",
                         re.IGNORECASE)
_LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+(.+)$")
_GHERKIN = re.compile(r"^\s*(?:[-*•]\s*)?(given|when|then|and)\b\s*(.+)$", re.IGNORECASE)
MAX_CRITERIA = 30


def acceptance_criteria(description: str) -> list[dict[str, str]]:
    """The ticket's acceptance criteria, deterministically (the reviewer gets them as a list):
    labelled lines (``AC1: …``, ``AK 2 - …``), else the list items under an "Acceptance criteria" heading, else
    Given/When/Then scenarios. ``[{id, text}]`` in order; ``[]`` when the ticket names none. Pure."""
    lines = str(description or "").splitlines()
    labelled = [(f"AC{int(match.group(2))}", match.group(3).strip()) for line in lines
                if (match := _AC_LABEL.match(line))]
    if labelled:
        return [{"id": ident, "text": text[:300]} for ident, text in dict(labelled).items()][:MAX_CRITERIA]
    found: list[str] = []
    inside = False
    for line in lines:
        if _AC_HEADING.match(line):
            inside = True
            continue
        if inside and line.strip().startswith("#"):
            break
        item = _LIST_ITEM.match(line) if inside else None
        if item:
            found.append(item.group(1).strip())
    if not found:
        scenario: list[str] = []
        for line in [*lines, ""]:
            step = _GHERKIN.match(line)
            if step and step.group(1).lower() == "given" and scenario:
                found.append(" ".join(scenario))
                scenario = []
            if step:
                scenario.append(line.strip().lstrip("-*• "))
            elif scenario and not line.strip():
                found.append(" ".join(scenario))
                scenario = []
    return [{"id": f"AC{index}", "text": text[:300]} for index, text in enumerate(found, 1)][:MAX_CRITERIA]


def acceptance_rows(criteria: list[dict[str, str]], rows: list[dict[str, Any]],
                    previous: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    """One row per parsed criterion with the reviewer's answer for it (by its id, else by shared words); without an
    answer the previous pass's row for it (an incremental pass: a follow-up commit never
    looks worse for criteria nobody re-assessed), else ``not_assessed``. Without parsed criteria: the reviewer's
    rows. Pure."""
    rows = [dict(row) for row in rows or [] if isinstance(row, dict) and row.get("criterion")]
    if not criteria:
        return rows
    before = {str(row.get("criterion") or "").split(":", 1)[0].strip().upper(): dict(row)
              for row in previous or [] if isinstance(row, dict) and row.get("criterion")}
    used: set[int] = set()

    def words(text: str) -> set[str]:
        return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 2}

    merged = []
    for criterion in criteria:
        ident = criterion["id"].lower()
        match = next((index for index, row in enumerate(rows) if index not in used and re.search(
            rf"\b{re.escape(ident)}\b", str(row.get("criterion")).lower())), None)
        if match is None:
            mine = words(criterion["text"])
            best = max(((len(mine & words(str(row.get("criterion")))) / max(len(mine), 1), index)
                        for index, row in enumerate(rows) if index not in used), default=(0.0, None))
            match = best[1] if best[0] >= 0.5 else None
        row = rows[match] if match is not None else {}
        if match is not None:
            used.add(match)
        elif criterion["id"].upper() in before and before[criterion["id"].upper()].get("status") != "not_assessed":
            earlier = before[criterion["id"].upper()]
            note = " (not re-checked after the change)" if criterion["id"] in _recheck_ids(criteria) else ""
            row = {"status": earlier.get("status"), "evidence": f"{earlier.get('evidence') or ''}{note}".strip()}
        merged.append({"criterion": f"{criterion['id']}: {criterion['text']}",
                       "status": str(row.get("status") or "not_assessed"),
                       "evidence": str(row.get("evidence") or ("" if row else "the review gave no answer for it"))})
    return merged


def _recheck_ids(criteria: list[dict[str, str]]) -> set[str]:
    return {item["id"] for item in criteria if item.get("recheck")}


_PATH = re.compile(r"[\w./-]+\.[A-Za-z0-9]{1,6}")


def to_reassess(criteria: list[dict[str, str]], previous: list[dict[str, Any]],
                delta_files: set[str]) -> list[dict[str, str]]:
    """The criteria an incremental pass asks again: every one not ``covered`` before, and a covered one whose
    evidence names a file the delta changes (marked ``recheck``). Pure."""
    before = {str(row.get("criterion") or "").split(":", 1)[0].strip().upper(): dict(row)
              for row in previous or [] if isinstance(row, dict)}
    asked = []
    for criterion in criteria:
        earlier = before.get(criterion["id"].upper())
        if earlier is None or earlier.get("status") != "covered":
            asked.append(dict(criterion))
            continue
        evidence = {path.lstrip("./") for path in _PATH.findall(str(earlier.get("evidence") or ""))}
        if any(path == changed or changed.endswith(f"/{path}") or path.endswith(f"/{changed}")
               for path in evidence for changed in delta_files):
            asked.append({**criterion, "recheck": True})
    return asked


def criteria_section(key: str, criteria: list[dict[str, str]]) -> dict[str, str]:
    """The reviewer's context section listing the criteria it answers one by one (``ACCEPTANCE_RULE``)."""
    return {"title": f"acceptance criteria of {key}",
            "text": "\n".join(f"{item['id']}: {item['text']}" for item in criteria)}


async def commit_messages(root: str, base: str, head: str) -> list[str]:
    if not root or not base or not head:
        return []
    code, out, _err = await safe_git.git(root, "log", f"--max-count={MAX_COMMITS}", "--format=%B%x00",
                                         f"{base}..{head}")
    return [part.strip() for part in out.split("\x00") if part.strip()] if code == 0 else []


async def jira_projects(db: AsyncSession, project_id: str) -> set[str]:
    """The Jira project keys the Workspace is connected to (its Jira intakes and its Jira knowledge sources)."""
    from ..knowledge.structured.tickets import jira_project_keys
    from ..workflow_routing.phased_start_jira import _jira_intakes, _project_keys

    keys = set().union(*(_project_keys(config) for config in await _jira_intakes(db, project_id)))
    return keys | {key.upper() for key in await jira_project_keys(db, project_id)}


async def _known(db: AsyncSession, project_id: str, keys: list[str]) -> WorkItem | None:
    if not keys:
        return None
    rows = (await db.execute(select(WorkItem).where(
        WorkItem.project_id == project_id, func.upper(WorkItem.source_key).in_(keys)))).scalars().all()
    by_key = {str(row.source_key or "").upper(): row for row in rows}
    return next((by_key[key] for key in keys if key in by_key), None)


async def _from_jira(db: AsyncSession, run: WorkflowRun, key: str) -> WorkItem | None:
    from ...models import User
    from ..workflow_routing.phased_start_jira import jira_work_item
    from ..workflow_runs.platform.dispatch import dispatch_tool

    read = await dispatch_tool(db, run, "get_jira_ticket", {"ticket_id": key}, capability_class="read_only")
    if not read.ok:
        logger.info("pr_review_bot.ticket_unreadable key=%s reason=%s", key, read.reason)
        return None
    issue = dict(read.result or {})
    user = await db.get(User, run.requested_by) if run.requested_by else None
    if user is None:
        return None
    return await jira_work_item(db, user=user, project_id=str(run.project_id), item={
        "title": str(issue.get("summary") or key), "description": str(issue.get("description") or "")},
        jira={"key": key, "id": issue.get("id"), "project_key": key.rsplit("-", 1)[0],
              "issue_type": str(issue.get("issue_type") or "Task")})


async def link_ticket(db: AsyncSession, run: WorkflowRun, facts: dict[str, Any], root: str, base: str,
                      head: str) -> dict[str, Any]:
    """Link the run to the pull request's ticket; what was found (``{key, source, title}``, ``{}`` for none)."""
    if not run.project_id:
        return {}
    keys = candidates(str(facts.get("source_branch") or ""), str(facts.get("title") or ""),
                      await commit_messages(root, base, head))
    item = await _known(db, str(run.project_id), keys)
    source = "workspace"
    if item is None:
        projects = await jira_projects(db, str(run.project_id))
        jira = next((key for key in keys if key.rsplit("-", 1)[0] in projects), "")
        try:
            item = await _from_jira(db, run, jira) if jira else None
        except Exception:  # noqa: BLE001 - a ticket that cannot be stored never stops the review
            logger.warning("pr_review_bot.ticket_not_stored key=%s", jira, exc_info=True)
            item = None
        source = "jira"
    if item is None:
        return {}
    run.work_item_id = item.id
    criteria = acceptance_criteria(str(item.description or ""))
    asked = criteria
    delta = str(dict(facts.get("incremental") or {}).get("from") or "")
    previous = list(dict(facts.get("previous_pass") or {}).get("acceptance") or [])
    if criteria and delta and previous:  # an incremental pass asks only what may have changed
        changed = (await safe_git.git(root, "diff", "--name-only", delta, head))[1].splitlines() if root else []
        asked = to_reassess(criteria, previous, {path.strip() for path in changed if path.strip()})
        criteria = [{**item, **({"recheck": True} if any(ask["id"] == item["id"] and ask.get("recheck")
                                                         for ask in asked) else {})} for item in criteria]
    if asked:
        context = dict(run.context or {})
        context["review_context_sections"] = [*(context.get("review_context_sections") or []),
                                              criteria_section(str(item.source_key or ""), asked)]
        run.context = context
    return {"key": str(item.source_key or ""), "source": source, "title": str(item.title or "")[:200],
            **({"criteria": criteria} if criteria else {})}


__all__ = ["KEY", "acceptance_criteria", "acceptance_rows", "candidates", "commit_messages", "criteria_section",
           "jira_projects", "link_ticket", "to_reassess"]
