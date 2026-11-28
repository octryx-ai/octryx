"""Rendering for unattended epic documentation: repository and run data only, everything escaped."""

from __future__ import annotations

import re
from html import escape
from typing import Any

from ....models import WorkflowRun
from ....models.runtime.secure_work import WorkItem


def _link(label: str, url: str) -> str:
    return f'<a href="{escape(url, quote=True)}">{escape(label)}</a>' if url else escape(label)


def _page_link(grant: dict[str, Any], slot: str, label: str) -> str:
    page = dict(dict(grant.get("pages") or {}).get(slot) or {})
    return f"<li>{label}: {_link(page.get('title') or slot, str(page.get('url') or ''))}</li>" if page else ""


def _pr(run: WorkflowRun) -> tuple[str, str]:
    pull_request = dict(run.pull_request or {})
    return str(pull_request.get("id") or ""), str(pull_request.get("url") or "")


def _item_link(item: WorkItem | None) -> str:
    if item is None:
        return ""
    return _link(f"{item.source_key}: {item.title}", str(item.source_url or ""))


_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")


def markdown_storage(text: str) -> str:
    # Everything is escaped so a file can never inject Confluence storage markup.
    out: list[str] = []
    paragraph: list[str] = []
    items: list[str] = []
    block: list[str] | None = None

    def flush() -> None:
        if paragraph:
            out.append(f"<p>{escape(' '.join(paragraph))}</p>")
            paragraph.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{escape(item)}</li>" for item in items) + "</ul>")
            items.clear()

    table: list[str] = []
    for line in str(text or "").splitlines():
        if block is not None:
            if line.strip().startswith("```"):
                out.append(f"<pre>{escape(chr(10).join(block))}</pre>")
                block = None
            else:
                block.append(line)
            continue
        if line.strip().startswith("|"):
            flush()
            table.append(line)
            continue
        if table:
            out.append(f"<pre>{escape(chr(10).join(table))}</pre>")
            table = []
        if line.strip().startswith("```"):
            flush()
            block = []
        elif heading := _HEADING.match(line):
            flush()
            level = min(len(heading.group(1)) + 1, 6)
            out.append(f"<h{level}>{escape(heading.group(2).strip())}</h{level}>")
        elif bullet := _BULLET.match(line):
            if paragraph:
                flush()
            items.append(bullet.group(1).strip())
        elif not line.strip():
            flush()
        elif items and line.startswith((" ", "\t")):
            items[-1] = f"{items[-1]} {line.strip()}"
        else:
            if items:
                flush()
            paragraph.append(line.strip())
    flush()
    if table:
        out.append(f"<pre>{escape(chr(10).join(table))}</pre>")
    if block is not None:
        out.append(f"<pre>{escape(chr(10).join(block))}</pre>")
    return "".join(out)
