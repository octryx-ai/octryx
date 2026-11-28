"""The specification for the reviewer."""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun, WorkItem
from ..workflow_runs import safe_git

MAX_SECTIONS, MAX_SPEC_CHARS, MAX_PAGES, MAX_PAGE_CHARS = 3, 8_000, 3, 8_000
_HEADING = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
_PAGE = re.compile(r"https?://[^\s)\]>\"']+?/wiki/[^\s)\]>\"']*?pages/(\d+)|[?&]pageId=(\d+)")
_TAG = re.compile(r"<[^>]+>")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")


def terms(changed: list[str], diff: str = "") -> set[str]:
    found = {part.lower() for path in changed for part in Path(path).with_suffix("").parts if len(part) > 3}
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            match = re.match(r"\+\s*(?:def|class|function|fun|func|const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)", line)
            if match:
                found.add(match.group(1).lower())
    return found


def sections(text: str) -> list[tuple[str, str]]:
    marks = list(_HEADING.finditer(text))
    if not marks:
        return [("", text)]
    out = [("", text[:marks[0].start()])] if text[:marks[0].start()].strip() else []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        out.append((mark.group(2).strip(), text[mark.start():end]))
    return out


def relevant(parts: list[tuple[str, str]], names: set[str], limit_sections: int, limit_chars: int) -> str:
    scored = []
    for index, (heading, body) in enumerate(parts):
        if "decision" in heading.lower():
            continue
        words = {word.lower() for word in _WORD.findall(body)}
        score = len(words & names)
        if score:
            scored.append((-score, index, body.strip()))
    chosen = sorted(sorted(scored)[:limit_sections], key=lambda item: item[1])
    text, used = [], 0
    for _score, _index, body in chosen:
        room = limit_chars - used - (2 if text else 0)  # the blank line between two parts counts too
        body = body[:max(0, room)]
        if body:
            text.append(body)
            used += len(body) + (2 if len(text) > 1 else 0)
    return "\n\n".join(text)


def repository_spec(root: str, changed: list[str], names: set[str]) -> tuple[str, str]:
    from ..workflow_runs.review.spec_decisions import spec_for_change

    if not root:
        return "", ""
    base = Path(root)
    spec = spec_for_change(base, tuple(changed))
    if spec is None:
        return "", ""
    text = relevant(sections(spec.read_text(encoding="utf-8", errors="replace")), names, MAX_SECTIONS,
                    MAX_SPEC_CHARS)
    return (spec.relative_to(base).as_posix(), text) if text else ("", "")


def page_ids(text: str) -> list[str]:
    ids = []
    for match in _PAGE.finditer(text or ""):
        page = match.group(1) or match.group(2)
        if page and page not in ids:
            ids.append(page)
    return ids[:MAX_PAGES]


def page_text(content: str) -> list[tuple[str, str]]:
    marked = re.sub(r"<h([1-3])[^>]*>(.*?)</h\1>", lambda m: "\n" + "#" * int(m.group(1)) + " " + m.group(2) + "\n",
                    content or "", flags=re.IGNORECASE | re.DOTALL)
    plain = html.unescape(_TAG.sub(" ", marked))
    return sections(re.sub(r"[ \t]+", " ", plain))


async def _confidential(db: AsyncSession, project_id: str) -> bool:
    from ...models.security.data_classification import CLASSIFICATION_CONFIDENTIAL
    from ..model_gateway.data_policy.classification import classification_rank
    from ..model_gateway.data_policy.source import resolve_workspace_data_classification

    level = await resolve_workspace_data_classification(db, project_id=project_id)
    if not level.resolved:
        return True  # unknown counts as the strict case
    rank, strict = classification_rank(level.classification), classification_rank(CLASSIFICATION_CONFIDENTIAL)
    return rank is None or strict is None or rank >= strict


async def _own_spaces(db: AsyncSession, project_id: str) -> set[str]:
    from ...tools._confluence_access import normalize_space_rules
    from ..project.service import get_project_config

    config = await get_project_config(project_id, db)
    return {rule["space_key"].upper() for rule in normalize_space_rules(config) if rule.get("enabled", True)}


async def confluence_pages(db: AsyncSession, run: WorkflowRun, names: set[str]) -> tuple[list[dict[str, Any]],
                                                                                         list[str]]:
    from ..workflow_runs.platform.dispatch import dispatch_tool

    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    ids = page_ids(str(item.description or "")) if item is not None else []
    if not ids:
        return [], []
    strict = await _confidential(db, str(run.project_id))
    own = await _own_spaces(db, str(run.project_id)) if strict else set()
    found, notes = [], []
    for page in ids:
        read = await dispatch_tool(db, run, "get_confluence_page", {"page_id": page}, capability_class="read_only")
        result = dict(read.result or {}) if read.ok else {}
        if not read.ok or result.get("error"):
            notes.append(f"Confluence page {page} not readable")
            continue
        space = str(result.get("space_key") or "").upper()
        if strict and space not in own:
            notes.append(f"Confluence page {page} left out: space {space or '?'} is not this confidential "
                         "Workspace's own")
            continue
        text = relevant(page_text(str(result.get("content") or result.get("body") or "")), names, MAX_SECTIONS,
                        MAX_PAGE_CHARS)
        if text:
            found.append({"title": f"specification page '{str(result.get('title') or page)[:80]}' ({space})",
                          "text": text, "page": {"id": page, "title": result.get("title"), "space": space,
                                                 "url": result.get("url")}})
    return found, notes


async def spec_context(db: AsyncSession, run: WorkflowRun, root: str, base: str, head: str) -> dict[str, Any]:
    changed = (await safe_git.git(root, "diff", "--name-only", base, head))[1].splitlines() if root and base else []
    diff = (await safe_git.git(root, *safe_git.DIFF, base, head))[1] if root and base else ""
    names = terms([path for path in changed if path.strip()], diff)
    path, text = repository_spec(root, changed, names)
    pages, notes = await confluence_pages(db, run, names)
    added = ([{"title": f"specification {path}: the sections this change touches", "text": text}] if text else [])
    added += [{"title": page["title"], "text": page["text"]} for page in pages]
    if added:
        context = dict(run.context or {})
        context["review_context_sections"] = [*(context.get("review_context_sections") or []), *added]
        run.context = context
    return {key: value for key, value in (("path", path), ("pages", [page["page"] for page in pages]),
                                          ("notes", notes)) if value}


__all__ = ["confluence_pages", "page_ids", "page_text", "relevant", "repository_spec", "sections", "spec_context",
           "terms"]
