"""The documentation page of a run: settings, title and rendered body."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun, WorkItem
from ..phase_outputs import OUTPUTS_KEY
from .record import KIND

SETTINGS_KEY = "feature_documentation"


@dataclass(frozen=True, slots=True)
class DocumentationSettings:
    space_key: str
    parent_page_id: str
    knowledge_connector_key: str


def documentation_settings(project_config: dict[str, Any] | None) -> DocumentationSettings | None:
    raw = dict((project_config or {}).get(SETTINGS_KEY) or {})
    space = str(raw.get("confluence_space_key") or "").strip().upper()
    if not space:
        return None
    return DocumentationSettings(space_key=space, parent_page_id=str(raw.get("parent_page_id") or "").strip(),
                                 knowledge_connector_key=str(raw.get("knowledge_connector_key") or "").strip())


def recorded_output(run: WorkflowRun, kind: str = KIND) -> dict[str, Any] | None:
    entry = dict(dict(run.context or {}).get(OUTPUTS_KEY) or {}).get(kind)
    return dict(entry) if isinstance(entry, dict) else None


async def run_links(db: AsyncSession, run: WorkflowRun) -> dict[str, Any]:
    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    ticket_url = item.source_url if item is not None and item.source_key == run.ticket_key else None
    pull_request = dict(run.pull_request or {})
    return {"ticket": {"key": run.ticket_key or "", "url": ticket_url or ""},
            "pull_request": {"id": str(pull_request.get("id") or ""), "url": str(pull_request.get("url") or "")}}


def page_title(run: WorkflowRun, record: dict[str, Any]) -> str:
    title = str(record.get("title") or run.title or "Feature").strip()
    return f"{run.ticket_key}: {title}"[:255] if run.ticket_key else title[:255]


def _paragraphs(text: str) -> str:
    return "".join(f"<p>{escape(part)}</p>" for part in str(text or "").split("\n\n") if part.strip())


def _link(label: str, url: str) -> str:
    return f'<a href="{escape(url, quote=True)}">{escape(label)}</a>' if url else escape(label)


def render_storage(record: dict[str, Any], criteria: list[dict[str, Any]], links: dict[str, Any], *,
                   run_id: str, run_marker: str = "") -> str:
    rows = "".join(
        f"<tr><td>{escape(item['id'])}</td><td>{escape(item['text'])}</td><td>"
        + ("manual check" if item.get("manual_only") else "<br/>".join(f"<code>{escape(test)}</code>"
                                                                          for test in item["tests"]))
        + "</td></tr>" for item in criteria)
    ticket, pull_request = links["ticket"], links["pull_request"]
    # First: the provenance line with the create marker (``target.marker``), read back to reconcile a lost create.
    sections = [
        f"<p><em>Published by Octryx workflow run {escape(run_id)}"
        + (f" ({escape(run_marker)})" if run_marker else "") + ".</em></p>",
        "<h2>What</h2>", _paragraphs(record["what"]),
        "<h2>Why</h2>", _paragraphs(record["why"]),
        "<h2>How to use</h2>", _paragraphs(record["how_to_use"]),
        "<h2>Acceptance criteria and tests</h2>",
        f"<table><tbody><tr><th>Criterion</th><th>Text</th><th>Tests</th></tr>{rows}</tbody></table>",
        "<h2>Links</h2><ul>",
        f"<li>Ticket: {_link(ticket['key'] or 'none', ticket['url'])}</li>" if ticket["key"] else "",
        f"<li>Pull request: {_link('#' + pull_request['id'], pull_request['url'])}</li>"
        if pull_request["url"] else "",
        "</ul>",
    ]
    if record.get("notes"):
        sections += ["<h2>Notes</h2>", _paragraphs(record["notes"])]
    return "".join(sections)


async def documentation_pages(db: AsyncSession, work_item_id: str) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from ....models import WorkItemDocument

    rows = (await db.execute(select(WorkItemDocument).where(WorkItemDocument.work_item_id == work_item_id)
                             .order_by(WorkItemDocument.updated_at.desc()))).scalars().all()
    return [{"provider": row.provider, "space_key": row.space_key, "page_id": row.page_id, "title": row.title,
             "url": row.url, "version": row.version, "run_id": row.run_id,
             "updated_at": row.updated_at.isoformat() if row.updated_at else None} for row in rows]
