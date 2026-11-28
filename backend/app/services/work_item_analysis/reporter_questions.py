"""Open questions to the Jira reporter: one comment per analysis, mentioning the reporter."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.connector_auth.atlassian_modes import JIRA

from ...models import AuditLog, WorkItem, WorkItemAnalysis
from ...time_utils import utc_now
from ...tools.jira_impl._jira_cloud import is_jira_cloud, text_to_adf
from ..connector_auth.atlassian import auth_headers, request_auth
from ..model_gateway.inbound.secret_scan import contains_secret
from ..outbound_egress import CONNECTION_JIRA, egress_transport
from ..secure_work.item_connection import work_item_connection_config
from ..secure_work.jira.jira_scope import parse_allowed_projects, writable_issue
from ..secure_work.lifecycle_transitions import default_workflow_for_item
from ..secure_work.sync_policy import executes, load_item_intake
from ..secure_work.workflow_mapping import normalize_workflow_mappings, normalize_workflow_states

logger = logging.getLogger(__name__)
AUDIT_ACTION = "work_item_analysis.reporter_question"
STATE_POSTED = "posted"
STATE_SKIPPED = "skipped"
STATE_FAILED = "failed"
STATE_PROPOSED = "proposed"
INTRO = "The automated analysis of this ticket has open questions. Could you answer them here?"
_TIMEOUT = 30


def _skipped(reason: str) -> dict[str, Any]:
    return {"state": STATE_SKIPPED, "reason": reason}


async def _write_back_reason(db: AsyncSession, item: WorkItem) -> str | None:
    workflow = await default_workflow_for_item(db, item)
    if workflow is None:
        return "no_workflow"
    await load_item_intake(db, item)
    if not executes(workflow.sync_policy_json, item):  # the intake's own sync_mode, else the workflow's
        return "jira_write_back_disabled"
    states = normalize_workflow_states(workflow.states_json)
    mapping = normalize_workflow_mappings(workflow.mappings_json, states=states).get(str(item.work_state or ""), {})
    return None if mapping.get("sync_back") else "jira_mapping_not_synced"


def _reporter(item: WorkItem) -> tuple[str, str]:
    fields = item.source_fields_json if isinstance(item.source_fields_json, dict) else {}
    people = fields.get("people") if isinstance(fields.get("people"), dict) else {}
    reporter = people.get("reporter") if isinstance(people.get("reporter"), dict) else {}
    return str(reporter.get("id") or item.reporter or "").strip(), str(reporter.get("display") or "").strip()


async def _search_user(client: httpx.AsyncClient, base_url: str, headers: dict[str, str], cloud: bool,
                       display: str) -> str:
    if not display:
        return ""
    path = "/rest/api/3/user/search" if cloud else "/rest/api/2/user/search"
    response = await client.get(f"{base_url}{path}", headers=headers,
                                params={"query": display} if cloud else {"username": display})
    if response.status_code >= 400:
        return ""
    users = response.json() if isinstance(response.json(), list) else []
    matches = [user for user in users if isinstance(user, dict) and user.get("displayName") == display]
    if len(matches) != 1:
        return ""
    return str(matches[0].get("accountId") or matches[0].get("name") or "")


def comment_body(questions: list[str], reporter: str, *, cloud: bool, marker: str = "") -> Any:
    lines = [f"* {question}" for question in questions]
    if not cloud:
        return "\n".join([f"[~{reporter}] {INTRO}", *lines, *([f"\n{marker}"] if marker else [])])
    listing = text_to_adf("\n".join(lines))
    mention = {"type": "paragraph", "content": [{"type": "mention", "attrs": {"id": reporter}},
                                                 {"type": "text", "text": f" {INTRO}"}]}
    tail = [{"type": "paragraph", "content": [{"type": "text", "text": marker}]}] if marker else []
    return {"type": "doc", "version": 1, "content": [mention, *(listing.get("content") or []), *tail]}


async def _post(db: AsyncSession, item: WorkItem, questions: list[str], marker: str = "") -> dict[str, Any]:
    config, refused = await work_item_connection_config(db, item, "jira")
    if refused:
        return _skipped(refused)
    base_url = str(config.get("jira_url") or "").rstrip("/")
    try:
        writable_issue(item.source_key, parse_allowed_projects(config.get("jira_allowed_projects")))
    except HTTPException:
        return _skipped("scope_not_allowed")
    authorization, http_auth = auth_headers(JIRA, config), request_auth(JIRA, config)
    if not base_url or not (authorization or http_auth):
        return _skipped("jira_not_configured")
    cloud = is_jira_cloud(base_url, config)
    headers = {**authorization, "Accept": "application/json", "Content-Type": "application/json"}
    stored, display = _reporter(item)
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, auth=http_auth,
                                 transport=egress_transport(CONNECTION_JIRA)) as client:
        reporter = stored or await _search_user(client, base_url, headers, cloud, display)
        if not reporter:
            return _skipped("reporter_unresolved")
        if contains_secret("\n".join(questions)):
            return _skipped("secret_detected")
        version = "3" if cloud else "2"
        response = await client.post(f"{base_url}/rest/api/{version}/issue/{item.source_key}/comment",
                                     headers=headers,
                                     json={"body": comment_body(questions, reporter, cloud=cloud, marker=marker)})
    if response.status_code >= 400:
        logger.warning("work_item_analysis_reporter_question_failed key=%s status=%s", item.source_key,
                       response.status_code)
        return {"state": STATE_FAILED, "reason": f"jira_http_{response.status_code}"}
    comment_id = response.json().get("id") if isinstance(response.json(), dict) else None
    return {"state": STATE_POSTED, "comment_id": str(comment_id or ""), "at": utc_now().isoformat(),
            "questions": len(questions)}


async def _marker(db: AsyncSession, actor_id: str) -> str:
    from ..ai_marking import MarkingFacts, marker_line
    from ..ai_marking_responsible import responsible_name

    name = await responsible_name(db, user_id=actor_id)
    return marker_line(MarkingFacts(responsible=name)) if name else ""


async def ask_reporter(db: AsyncSession, *, item: WorkItem, analysis: WorkItemAnalysis, ask: bool,
                       actor_id: str, confirmed_by_person: bool = False) -> dict[str, Any]:
    questions = list((analysis.analysis_json or {}).get("open_questions") or [])
    if not questions:
        return _skipped("no_open_questions")
    if not ask:
        result = _skipped("ask_reporter_off")
    elif str(item.source_type or "") != "jira":
        result = _skipped("not_a_jira_item")
    elif (reason := await _write_back_reason(db, item)) is not None:
        result = _skipped(reason)
    elif (analysis.reporter_question or {}).get("state") == STATE_POSTED:
        return _skipped("already_posted")
    elif str(analysis.mode or "") == "auto" and not confirmed_by_person:
        result = {"state": STATE_PROPOSED, "reason": "awaits_person", "questions": len(questions)}
    else:
        try:
            result = await _post(db, item, questions, await _marker(db, actor_id))
        except httpx.HTTPError:
            result = {"state": STATE_FAILED, "reason": "jira_unreachable"}
    db.add(AuditLog(user_id=actor_id, action=AUDIT_ACTION, resource_type="work_item", resource_id=item.id,
                    project_id=item.project_id,
                    details={"analysis_id": analysis.id, "project_id": item.project_id, **result}))
    return result


async def post_proposed_questions(db: AsyncSession, *, item: WorkItem, analysis: WorkItemAnalysis, ask: bool,
                                  person_id: str) -> dict[str, Any]:
    if (analysis.reporter_question or {}).get("state") != STATE_PROPOSED:
        return _skipped("nothing_proposed")
    return await ask_reporter(db, item=item, analysis=analysis, ask=ask, actor_id=person_id, confirmed_by_person=True)


__all__ = ["AUDIT_ACTION", "STATE_FAILED", "STATE_POSTED", "STATE_PROPOSED", "STATE_SKIPPED", "ask_reporter",
           "comment_body", "post_proposed_questions"]
