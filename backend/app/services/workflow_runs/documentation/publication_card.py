"""Statement (b): the publication card, its page body, target and the pending banner while (a) is open."""

from __future__ import annotations

import difflib
from datetime import datetime
from html import escape
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun, WorkflowRunDecision
from ....time_utils import ensure_utc
from ..graph import ACCEPTED, SUBJECT_PUBLICATION
from .acceptance import FINAL_STATUS, MAX_DIFF_LINES, STATE_PENDING, _iso, acceptance_state, confirmed_criteria
from .s1_graph import facts


def pending_banner(as_of: str, link: str, run_id: str) -> str:
    return (f"<p><strong>Functional acceptance pending as of {escape(as_of)}.</strong> This version was published "
            "before the functional acceptance was recorded; a later acceptance is a separate, dated decision on "
            f'workflow run <a href="{escape(link, quote=True)}">{escape(run_id)}</a> and does not change this '
            "version.</p>")


def _later(*values: Any) -> str:
    stamps = [ensure_utc(datetime.fromisoformat(value) if isinstance(value, str) else value)
              for value in values if value is not None]
    return _iso(max(stamps)) if stamps else ""


async def _final_output(db: AsyncSession, run: WorkflowRun) -> dict[str, Any] | None:
    from ..graph import graph_for_run
    from .page import recorded_output

    output = recorded_output(run)
    if output is None:
        return None
    node = (await graph_for_run(db, run)).nodes.get(str(output.get("node_id") or ""))
    return output if node is not None and node.config.get("documentation_status") == FINAL_STATUS else None


async def _previous_body(db: AsyncSession, run: WorkflowRun) -> str:
    decision_id = str(facts(run).get("publication_decision_id") or "")
    decision = await db.get(WorkflowRunDecision, decision_id) if decision_id else None
    return str(dict(decision.payload or {}).get("body") or "") if decision is not None else ""


def _diff(before: str, after: str) -> list[str]:
    split = (lambda text: text.replace("><", ">\n<").splitlines())  # noqa: E731
    lines = list(difflib.unified_diff(split(before), split(after), "previous", "now", lineterm="", n=1))
    return lines[:MAX_DIFF_LINES]


async def publication_payload(db: AsyncSession, run: WorkflowRun) -> dict[str, Any]:
    from ....tools._confluence_storage import normalize_storage_content
    from ....tools.confluence import storage_sha256
    from ...project.service import get_project_config
    from .page import page_title, render_storage, run_links
    from .preflight import audience_settings, run_link
    from .s1_graph import active_intent

    payload: dict[str, Any] = {"subject": SUBJECT_PUBLICATION}
    output = await _final_output(db, run)
    if output is None:
        return {**payload, "missing": "The final documentation (after the merge) is not recorded yet."}
    state = acceptance_state(run)
    if state["state"] not in (ACCEPTED, STATE_PENDING):
        return {**payload, "missing": "The functional acceptance (a) was not decided; it comes first."}
    intent = await active_intent(db, run)
    if intent is None:
        return {**payload, "missing": "No publication was reserved yet (operation and marker)."}
    audience = audience_settings(await get_project_config(run.project_id, db))
    record = dict(output.get("record") or {})
    criteria, links = await confirmed_criteria(db, run), await run_links(db, run)
    blockers: list[str] = []
    if not criteria:
        blockers.append("no human-confirmed acceptance criteria are recorded")
    if intent.title != page_title(run, record):
        blockers.append(f"the reserved publication is for the title '{intent.title}', the documentation now says "
                        f"'{page_title(run, record)}': reserve it again")
    pending = state["state"] == STATE_PENDING
    as_of = _later(intent.created_at, state.get("as_of")) if pending else ""
    link = run_link(run)
    banner = pending_banner(as_of, link, run.id) if pending and link else ""
    if pending and not link:
        blockers.append("the page cannot link the run: the platform's public origin is not configured")
    body = banner + render_storage(record, criteria, links, run_id=run.id, run_marker=intent.marker)
    previous = await _previous_body(db, run)
    payload.update(
        title=intent.title, output_version=output.get("version"), output_hash=output.get("hash"),
        acceptance_criteria=criteria, links=links, body=body,
        canonical_hash=storage_sha256(normalize_storage_content(body)),
        target={"workspace_id": run.project_id, "operation": intent.operation,
                "operation_id": intent.operation_id, "marker": intent.marker,
                "connection_id": intent.connection_id, "instance": intent.instance, "space_id": intent.space_id,
                "space_key": intent.space_key, "parent_id": intent.parent_id, "page_id": intent.page_id,
                "base_version": intent.base_version, "expected_version": intent.expected_version,
                "summary": (f"new page under {intent.parent_id}" if intent.operation == "create"
                            else f"update of page {intent.page_id} from version {intent.base_version}")},
        audience={**(audience.to_dict() if audience else {}), "workspace_id": run.project_id},
        acceptance={"state": state["state"], "decision_id": state.get("decision_id"),
                    "decided_at": state.get("as_of")},
        acceptance_pending=pending, acceptance_as_of=as_of or None, run_link=link or None,
        storage_diff=_diff(previous, body) if previous and previous != body else [],
    )
    if audience is None:
        blockers.append("no audience is configured")
    if blockers:
        payload["blockers"] = blockers
    return payload
