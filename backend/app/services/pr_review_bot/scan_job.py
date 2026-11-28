"""The review's scan on a review seat's device (tool runner; ``devices/tool_jobs``)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, WorkflowRun
from . import scanners as scanner_data
from .diff_lines import parse_diff
from .scan_findings import ScanResult, changed_lines, scan_findings, to_facts

logger = logging.getLogger(__name__)

PURPOSE = "pr_review.scan"
FILES, RULES = "files", "rules"
STEP_TIMEOUT = 240
JOB_TIMEOUT = 900


async def _candidates(db: AsyncSession, run: WorkflowRun) -> list[str]:
    from ..devices.tool_jobs import devices_of
    from .seat_choice import bot_seat_phases

    people = [person.user.id for phase in await bot_seat_phases(db, run) for person in phase]
    return await devices_of(db, list(dict.fromkeys(people))) if people else []


def _steps(chosen: list[dict[str, Any]], with_rules: bool) -> list[dict[str, Any]]:
    steps = []
    for entry in chosen:
        report = str(entry.get("report") or f"{entry['id']}.sarif")
        args = scanner_data.command(entry, root=f"{{archive:{FILES}}}", report=f"{{out:{report}}}",
                                    rules=f"{{archive:{RULES}}}" if with_rules else "")
        steps.append({"id": entry["id"], "tool": entry["id"], "args": args, "outputs": [report],
                      "timeout": STEP_TIMEOUT})
    return steps


async def offer_scan(db: AsyncSession, run: WorkflowRun, *, root: str, head: str, diff: str) -> dict[str, Any]:
    from ..devices import tool_jobs, tree_archive
    from ..engineering_knowledge import stacks as stack_data

    changed = changed_lines(parse_diff(diff))
    project = await db.get(Project, run.project_id)
    chosen = scanner_data.selected(sorted(changed), await stack_data.for_project(db, project))
    if not chosen or not root:
        return {"notes": []} if not changed else {"notes": ["no scanner configured for these files"]}
    candidates = await _candidates(db, run)
    if not candidates:
        return {"notes": ["not scanned: no review seat device"]}
    rules, notes = [], []
    for entry in chosen:
        files, left_out = scanner_data.rule_entries(entry)
        rules += files
        notes += left_out
    files = tree_archive.build_from_git(Path(root), head, name=FILES, paths=sorted(changed))
    archives = [files] + ([tree_archive.build_archive(rules, name=RULES)] if rules else [])
    job = await tool_jobs.offer(db, purpose=PURPOSE, candidates=candidates, archives=archives,
                                steps=_steps(chosen, bool(rules)), needs=[], requested_by=run.requested_by,
                                workspace_id=str(run.project_id), timeout_seconds=JOB_TIMEOUT)
    return {"job_id": job.id, "scanners": chosen, "skipped": list(files.skipped), "notes": notes,
            "changed": {path: sorted(lines) for path, lines in changed.items()}}


def _reports(offered: dict[str, Any], steps: list[dict[str, Any]], result: ScanResult) -> list[tuple[dict, dict]]:
    by_id = {str(entry["id"]): entry for entry in offered.get("scanners") or []}
    reports = []
    for step in steps:
        entry = by_id.get(str(step.get("id")))
        if entry is None:
            continue
        report = str(entry.get("report") or f"{entry['id']}.sarif")
        if step.get("status") != "ok":
            missing = step.get("status") == "missing"
            result.notes.append(f"{entry['id']} {'not available on the device' if missing else step.get('status')}")
            continue
        try:
            reports.append((entry, json.loads(str(dict(step.get("files") or {}).get(report) or ""))))
        except ValueError:
            result.notes.append(f"{entry['id']} wrote no readable report")
    return reports


async def read_scan(db: AsyncSession, offered: dict[str, Any]) -> dict[str, Any]:
    from ..devices.tool_jobs import result as job_result

    notes = list(offered.get("notes") or [])
    if offered.get("skipped"):
        notes.append(f"{len(offered['skipped'])} file(s) too large to scan")
    if not offered.get("job_id"):
        return {"findings": [], "tools": [], "dropped": 0, "notes": notes}
    answer = await job_result(db, str(offered["job_id"]))
    if answer is None:
        return {"findings": [], "tools": [], "dropped": 0, "notes": [*notes, "scan still running"]}
    if answer["state"] != "done":
        return {"findings": [], "tools": [], "dropped": 0,
                "notes": [*notes, f"scan {answer['state']}: {answer.get('reason') or ''}".strip(": ")]}
    probe = ScanResult()
    reports = _reports(offered, list(answer.get("steps") or []), probe)
    changed = {path: set(lines) for path, lines in dict(offered.get("changed") or {}).items()}
    scanned = scan_findings(reports, root=FILES, changed=changed)
    return {**to_facts(scanned), "notes": [*notes, *probe.notes, *scanned.notes]}


__all__ = ["PURPOSE", "offer_scan", "read_scan"]
