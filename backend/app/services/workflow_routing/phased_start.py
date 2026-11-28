"""Start a phased workflow from the chat with one confirmation: the Work item and its workflow run."""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ...models import Approval, Message, User, WorkItem
from ...models import Session as AgentSession
from .proposal_contract import split_instruction
from .proposal_states import WORKFLOW_PROPOSAL_KEY
from .workflow_selection import ROUTING_RESOLUTION_KEY

logger = logging.getLogger(__name__)

# The kind of Work item each shipped workflow works on: spec-writing splits an epic into stories
# (``work.create_stories`` refuses anything else), epic-delivery builds an epic's stories; any other workflow
# works on a task. Platform items know no "story" type (``teamwork.stories.PLATFORM_STORY_TYPE``): a story (an
# existing Jira story the card names) is stored as a task.
_ITEM_TYPE_BY_WORKFLOW = {"spec-writing": "epic", "epic-delivery": "epic", "bug-fix-reproduction": "bug"}
_PLATFORM_TYPE = {"story": "task"}
_TYPE_LABELS = {"epic": "Epic", "story": "Story", "task": "Task", "bug": "Bug"}
_ITEM_KEY = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
# 'Hello Kitchen', "Hello Kitchen", „Hello Kitchen“, «Hello Kitchen», “Hello Kitchen”.
_QUOTED = re.compile(r"'([^'\n]{2,})'|\"([^\"\n]{2,})\"|„([^“”\n]{2,})[“”]|«([^»\n]{2,})»|“([^”\n]{2,})”")
_JIRA_PROJECT = re.compile(r"\bJira[- ]?(?:Projekt|project)\s+[„\"']?([A-Z][A-Z0-9]+)\b", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s|\n")
_TITLE_MAX = 500  # the Work item column

ANSWER_OTHER = "other"


def _text(value: Any) -> str:
    return str(value or "").strip()


def item_type_for(workflow_key: str) -> str:
    return _ITEM_TYPE_BY_WORKFLOW.get(workflow_key, "task")


def derived_title(message: str) -> str:
    instruction, _quoted = split_instruction(message)
    match = _QUOTED.search(instruction) or _QUOTED.search(message)
    if match:
        return next(group for group in match.groups() if group).strip()[:_TITLE_MAX]
    first = _SENTENCE_END.split(_text(instruction) or _text(message), maxsplit=1)[0]
    return first.strip().rstrip(".!?")[:_TITLE_MAX]


def named_jira_project(message: str) -> str | None:
    match = _JIRA_PROJECT.search(message or "")
    return match.group(1).upper() if match else None


async def _stored_item(db: AsyncSession, session: AgentSession, keys: list[str]) -> WorkItem | None:
    from ..work_item_analysis.seat_session import items_by_key

    for key in keys if session.project_id else ():
        items = await items_by_key(db, session.project_id, key)
        if len(items) == 1:
            return items[0]
    return None


async def _followed_item(db: AsyncSession, session: AgentSession) -> WorkItem | None:
    from ..work_item_analysis.seat_session import pinned_item_id
    from ..workflow_runs.records import active_run_for_session

    pinned = pinned_item_id(session)
    if pinned:
        return await db.get(WorkItem, pinned)
    run = await active_run_for_session(db, session.id)
    return await db.get(WorkItem, run.work_item_id) if run is not None and run.work_item_id else None


def _jira_item_view(issue: dict[str, Any], workflow_key: str) -> dict[str, Any]:
    kind = _text(issue["issue_type"]).lower() or item_type_for(workflow_key)
    return {"mode": "existing", "type": kind, "type_label": _TYPE_LABELS.get(kind, kind.title()),
            "title": issue["title"][:_TITLE_MAX], "description": issue["description"], "key": issue["key"],
            "id": None, "source": "jira"}


async def _bound_item(db: AsyncSession, session: AgentSession, workflow_key: str, message: str) -> dict[str, Any]:
    from .phased_start_jira import read_jira_issue

    instruction, _quoted = split_instruction(message)
    keys = list(dict.fromkeys(_ITEM_KEY.findall(instruction)))
    stored = await _stored_item(db, session, keys)
    if stored is not None:
        return _item_view(stored, workflow_key, message)
    for key in keys if session.project_id else ():
        issue = await read_jira_issue(db, session=session, key=key)
        if issue is not None:
            return _jira_item_view(issue, workflow_key)
    return _item_view(await _followed_item(db, session), workflow_key, message)


def _item_view(item: WorkItem | None, workflow_key: str, message: str) -> dict[str, Any]:
    if item is not None:
        kind = _text(item.issue_type).lower() or item_type_for(workflow_key)
        return {"mode": "existing", "type": kind, "type_label": _TYPE_LABELS.get(kind, kind.title()),
                "title": item.title or "", "description": item.description or "", "key": item.source_key,
                "id": item.id}
    kind = item_type_for(workflow_key)
    return {"mode": "new", "type": kind, "type_label": _TYPE_LABELS[kind], "title": derived_title(message),
            "description": _text(message), "key": None, "id": None}


def start_summary(workflow_title: str, item: dict[str, Any]) -> str:
    if item["mode"] == "existing":
        return f"Start {workflow_title} for {item['type_label']} {item['key']} '{item['title']}'"
    return f"Start {workflow_title} for a new {item['type_label']} '{item['title']}'"


def approval_text(start: dict[str, Any]) -> str:
    run_on = start["run_on"]
    label = next((option["label"] for option in run_on["options"] if option["key"] == run_on["default"]),
                 run_on["default"])
    steps = " → ".join(step["title"] for step in start["steps"] if step["title"])
    item = start["work_item"]
    creates = "" if item["mode"] == "existing" else f" It creates the {item['type_label']} and starts the run."
    jira = f" {start['jira']['label']}." if start.get("jira") else ""
    repository = repository_line(start)
    return (f"{start['summary']} (run on: {label}).{repository}{jira}{creates}"
            + (f" Steps: {steps}." if steps else ""))


def held_turn_message(session: AgentSession) -> str | None:
    record = _proposal(session) or {}
    start = record.get("start") if record.get("phased") else None
    if not isinstance(start, dict):
        return None
    item = start["work_item"]
    named = f"{item['type_label']} {item['key']} '{item['title']}'" if item.get("key") else (
        f"{item['type_label']} '{item['title']}'")
    return (f"Start {start['workflow_title']} for {named}? Check the draft below and press Start, choose another "
            "workflow, or don't start.")


def repository_line(start: dict[str, Any]) -> str:
    from .phased_start_repository import missing_text

    repository = start.get("repository")
    if not repository:
        return ""
    return f" Repository: {repository['ref']}." if repository.get("ref") else f" {missing_text(repository)}"


async def build_start_draft(db: AsyncSession, *, session: AgentSession, workflow_key: str, message: str
                            ) -> dict[str, Any]:
    from ..run_admission.phased_catalog import _phases
    from ..workflow_runs.engine import published_phased_flow
    from ..workflow_runs.runtime_target.target import target_choices
    from .phased_start_jira import jira_scope

    phased = await published_phased_flow(db, workflow_key, session.project_id)
    title = phased[0].name if phased else workflow_key
    definition = dict(phased[1].definition_json or {}) if phased else {}
    steps = [{"title": _text(node.get("label") or node.get("id"))} for node in _phases(definition)]
    item = await _bound_item(db, session, workflow_key, message)
    user = await db.get(User, session.user_id)
    choices = await target_choices(db, user=user, project_id=session.project_id)
    run_on = {"options": [{key: option[key] for key in ("key", "label", "help", "online") if key in option}
                          for option in choices["options"]], "default": choices["default"]}
    jira_project = named_jira_project(message)
    # The Jira issue is in the scope of this one confirmation: created first, then the item.
    jira = await jira_scope(db, project_id=session.project_id, named_project=jira_project, definition=definition,
                            item=item)
    from .phased_start_repository import missing_text, repository_choice

    # The run works in a repository: resolved now and shown, never discovered empty after the start.
    repository = await repository_choice(db, project_id=session.project_id, message=message, definition=definition,
                                         item_id=item["id"])
    notes = [text for text in (missing_text(repository),) if text]
    if not session.project_id:
        notes.append("This chat has no Workspace: choose one before starting a workflow run.")
    return {"workflow_key": workflow_key, "workflow_title": title, "work_item": item,
            "project_id": session.project_id, "jira_project": jira["project_key"] if jira else jira_project,
            "jira": jira, "repository": repository, "run_on": run_on, "steps": steps,
            "summary": start_summary(title, item), "notes": notes}


async def held_request_text(db: AsyncSession, session: AgentSession) -> str:
    from ..session.turn_approval_state import PAUSED_TURNS_METADATA_KEY
    from .proposal_decision import _pending_message_text

    paused = dict(session.metadata_ or {}).get(PAUSED_TURNS_METADATA_KEY)
    for entry in reversed(list(paused.values()) if isinstance(paused, dict) else []):
        message = await db.get(Message, _text(entry.get("user_message_id"))) if isinstance(entry, dict) else None
        if message is not None and message.session_id == session.id and message.role == "user":
            return _text(message.content)
    return await _pending_message_text(db, session)


def _proposal(session: AgentSession) -> dict[str, Any] | None:
    resolution = dict(session.metadata_ or {}).get(ROUTING_RESOLUTION_KEY)
    record = resolution.get(WORKFLOW_PROPOSAL_KEY) if isinstance(resolution, dict) else None
    return record if isinstance(record, dict) else None


def update_proposal(session: AgentSession, **fields: Any) -> dict[str, Any]:
    metadata = dict(session.metadata_ or {})
    resolution = dict(metadata.get(ROUTING_RESOLUTION_KEY) or {})
    record = {**dict(resolution.get(WORKFLOW_PROPOSAL_KEY) or {}), **fields}
    resolution[WORKFLOW_PROPOSAL_KEY] = record
    metadata[ROUTING_RESOLUTION_KEY] = resolution
    session.metadata_ = metadata
    flag_modified(session, "metadata_")
    return record


async def attach_start_draft(db: AsyncSession, *, session: AgentSession, message: str) -> dict[str, Any] | None:
    record = _proposal(session) or {}
    if not record.get("phased"):
        return None
    if isinstance(record.get("start"), dict):
        return record["start"]
    start = await build_start_draft(db, session=session, workflow_key=_text(record.get("workflow_key")),
                                    message=message)
    update_proposal(session, start=start)
    return start



class OtherWorkflowRefusedError(ValueError):
    pass


async def choose_other_workflow(db: AsyncSession, *, session: AgentSession, workflow_key: str,
                                message: str) -> dict[str, Any]:
    from sqlalchemy import select

    from .explicit_selection import list_published_workflow_definitions
    from .proposal_approval import proposal_approval_action

    key = _text(workflow_key)
    catalog = {entry["key"]: entry for entry in await list_published_workflow_definitions(
        db, project_id=session.project_id)}
    entry = catalog.get(key)
    if entry is None:
        raise OtherWorkflowRefusedError(f"'{key}' is not a workflow you can choose here.")
    update_proposal(
        session, workflow_key=key, workflow_title=entry.get("title") or key, phased=True, change_capable=True,
        reason="Chosen by the user.", reason_code="user_chose_other", start=None, started=None)
    record = update_proposal(session, start=await build_start_draft(db, session=session, workflow_key=key,
                                                                    message=message))
    approval = (await db.execute(select(Approval).where(
        Approval.session_id == session.id, Approval.action == proposal_approval_action(record["proposal_id"]),
        Approval.status == "pending"))).scalars().first()
    if approval is not None:
        approval.reason = approval_text(record["start"])
    await db.flush()
    return record


def choose_repository(session: AgentSession, value: str) -> bool:
    from .phased_start_repository import choose

    start = dict((_proposal(session) or {}).get("start") or {})
    chosen = choose(dict(start.get("repository") or {}), value) if start.get("repository") else None
    if chosen is None:
        return False
    update_proposal(session, start={**start, "repository": chosen})
    return True


def workspace_missing(session: AgentSession) -> bool:
    record = _proposal(session) or {}
    return bool(record.get("phased")) and not _text(dict(record.get("start") or {}).get("project_id"))


def repository_missing(session: AgentSession) -> str | None:
    from .phased_start_repository import missing_text

    record = _proposal(session) or {}
    return missing_text(dict(record.get("start") or {}).get("repository")) if record.get("phased") else None


def choose_run_location(session: AgentSession, run_on: str, *, model: str = "") -> None:
    start = dict((_proposal(session) or {}).get("start") or {})
    options = {option["key"] for option in dict(start.get("run_on") or {}).get("options") or []}
    if start and run_on in options:
        update_proposal(session, start={**start, "run_on": {**start["run_on"], "chosen": run_on,
                                                            "model": model.strip()}})


def choose_budget(session: AgentSession, budget: dict) -> None:
    start = dict((_proposal(session) or {}).get("start") or {})
    if start:
        update_proposal(session, start={**start, "budget": dict(budget)})


def chosen_start(session: AgentSession) -> dict:
    return dict((_proposal(session) or {}).get("start") or {})


__all__ = [
    "ANSWER_OTHER",
    "OtherWorkflowRefusedError",
    "approval_text",
    "attach_start_draft",
    "build_start_draft",
    "choose_other_workflow",
    "choose_repository",
    "repository_missing",
    "choose_run_location",
    "chosen_start",
    "choose_budget",
    "derived_title",
    "item_type_for",
    "named_jira_project",
]
