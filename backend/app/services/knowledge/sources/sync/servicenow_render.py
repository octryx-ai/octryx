"""Deterministic renderings of ServiceNow knowledge articles and records. Volatile fields are never rendered, so a touch
yields no new revision."""

from __future__ import annotations

import html
from typing import Any

MAX_FIELD_CHARS = 200
MAX_BODY_CHARS = 60_000

ARTICLE_FIELDS = "sys_id,number,short_description,article_type,text,wiki"
RECORD_FIELDS = (
    "sys_id,number,short_description,description,state,priority,impact,urgency,category,subcategory,"
    "assignment_group,cmdb_ci,business_service,opened_at,resolved_at,closed_at,close_code,close_notes,"
    "problem_state,known_error,workaround,cause_notes,fix_notes,comments"
)
_FACTS = (
    ("State", "state"),
    ("Problem state", "problem_state"),
    ("Priority", "priority"),
    ("Impact", "impact"),
    ("Urgency", "urgency"),
    ("Category", "category"),
    ("Subcategory", "subcategory"),
    ("Assignment group", "assignment_group"),
    ("Configuration item", "cmdb_ci"),
    ("Business service", "business_service"),
    ("Known error", "known_error"),
    ("Opened", "opened_at"),
    ("Resolved", "resolved_at"),
    ("Closed", "closed_at"),
    ("Close code", "close_code"),
)
_SECTIONS = (
    ("Description", "description"),
    ("Workaround", "workaround"),
    ("Cause", "cause_notes"),
    ("Fix", "fix_notes"),
    ("Resolution", "close_notes"),
    ("Comments", "comments"),
)


def _field(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("display_value") or value.get("value")
    if value is None or isinstance(value, dict | list):
        return ""
    return " ".join(str(value).split())[:MAX_FIELD_CHARS]


def _body(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("display_value") or value.get("value")
    if not isinstance(value, str):
        return ""
    return value.replace("\r\n", "\n").strip()[:MAX_BODY_CHARS]


def item_title(record: dict[str, Any], fallback: str) -> str:
    number, summary = _field(record.get("number")), _field(record.get("short_description"))
    if number and summary:
        return f"{number}: {summary}"
    return number or summary or fallback


def render_article(record: dict[str, Any], title: str) -> tuple[bytes, str]:
    if _field(record.get("article_type")) == "wiki":
        text = _body(record.get("wiki"))
        return f"# {title}\n\n{text}\n".encode(), "text/markdown"
    body = record.get("text")
    if not isinstance(body, str):
        body = ""
    escaped = html.escape(title)
    document = (
        f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{escaped}</title></head>'
        f"<body><h1>{escaped}</h1>{body}</body></html>"
    )
    return document.encode("utf-8"), "text/html"


def render_record(table: str, record: dict[str, Any], title: str) -> bytes:
    lines = [f"# {title}", "", f"- Table: {table}"]
    lines.extend(
        f"- {label}: {value}" for label, value in ((lab, _field(record.get(key))) for lab, key in _FACTS) if value
    )
    for heading, key in _SECTIONS:
        text = _body(record.get(key))
        if text:
            lines.extend(["", f"## {heading}", "", text])
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


__all__ = ["ARTICLE_FIELDS", "RECORD_FIELDS", "item_title", "render_article", "render_record"]
