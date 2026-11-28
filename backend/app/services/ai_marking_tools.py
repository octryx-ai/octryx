"""The one place a write tool's agent-written text gets its marker line, before approval, preview and fingerprint."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from .ai_marking import MarkingFacts, marking_facts, with_marker, with_storage_marker


@dataclass(frozen=True)
class Marked:
    fields: tuple[str, ...]
    # A created object always carries the line, even without a text of its own; an update only marks text it sends.
    always: bool = False
    storage: bool = False


_PR_CREATE = Marked(("description",), always=True)
_DESCRIPTION = Marked(("description",))
_REVIEW = Marked(("summary", "comment"))
MARKED_TOOLS: dict[str, Marked] = {
    "create_github_pull_request": _PR_CREATE,
    "create_gitlab_merge_request": _PR_CREATE,
    "create_bitbucket_pull_request": _PR_CREATE,
    "update_github_pull_request": _DESCRIPTION,
    "update_gitlab_merge_request": _DESCRIPTION,
    "update_bitbucket_pull_request": _DESCRIPTION,
    "add_bitbucket_pull_request_comment": Marked(("text",)),
    "post_github_pull_request_review": _REVIEW,
    "post_gitlab_merge_request_review": _REVIEW,
    "post_bitbucket_pull_request_review": _REVIEW,
    "create_github_issue": Marked(("body",), always=True),
    "update_github_issue": Marked(("body",)),
    "add_jira_comment": Marked(("body",)),
    "create_jira_ticket": Marked(("description",), always=True),
    "update_jira_ticket": _DESCRIPTION,
    "add_confluence_comment": Marked(("body",), storage=True),
    "create_confluence_page": Marked(("content",), always=True, storage=True),
    "update_confluence_page": Marked(("content",), storage=True),
    "ask_reporter_via_teams": Marked(("question",)),
    "create_issue": Marked(("description",), always=True),
    "update_issue": _DESCRIPTION,
    "create_meeting": Marked(("body",), always=True),
    "send_meeting_invite": Marked(("body",), always=True),
    "create_incident": Marked(("description",)),
    "update_incident": Marked(("body",)),
    "acknowledge": Marked(("message",)),
    "escalate": Marked(("message",)),
    "resolve": Marked(("message",)),
}


_PLATFORM_TEXT: ContextVar[bool] = ContextVar("platform_text", default=False)


@contextmanager
def platform_text() -> Iterator[None]:
    # Text the platform sends for a run but no agent wrote (a Work item's own words, a link line) stays unmarked.
    token = _PLATFORM_TEXT.set(True)
    try:
        yield
    finally:
        _PLATFORM_TEXT.reset(token)


def _marked_text(text: str, facts: MarkingFacts, *, storage: bool) -> str:
    if storage:
        from ..tools._confluence_storage import normalize_storage_content

        # Normalised here so the line is its own paragraph, never run into a plain-text page's one paragraph.
        return with_storage_marker(normalize_storage_content(text), facts)
    return with_marker(text, facts)


def mark_fields(tool_name: str, params: dict[str, Any], facts: MarkingFacts | None) -> dict[str, Any]:
    marked = MARKED_TOOLS.get(tool_name)
    if marked is None or facts is None or not isinstance(params, dict):
        return params
    changed = dict(params)
    sent = [name for name in marked.fields if isinstance(params.get(name), str) and params[name].strip()]
    if not sent and marked.always:
        sent = [marked.fields[0]]
    for name in sent:
        changed[name] = _marked_text(str(params.get(name) or ""), facts, storage=marked.storage)
    return changed


async def marked_arguments(tool_name: str, params: Any, context: Any) -> Any:
    if tool_name not in MARKED_TOOLS or not isinstance(params, dict) or _PLATFORM_TEXT.get():
        return params
    if MARKED_TOOLS[tool_name] is _PR_CREATE:
        from .workflow_runs.pr_links import with_session_links

        params = await with_session_links(params, context)
    return mark_fields(tool_name, params, await marking_facts(context))
