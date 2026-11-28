"""Execute workflow-mapped Jira transitions for work-item state changes."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.connector_auth.atlassian_modes import JIRA
from app.services.outbound_egress import CONNECTION_JIRA, egress_transport

from ....models import WorkItem, WorkItemWorkflowDefinition
from ....tools.jira_impl._jira_cloud import is_jira_cloud, rich_text_body
from ...connector_auth.atlassian import auth_headers, request_auth
from ..item_connection import work_item_connection_config
from ..sync_policy import executes, load_item_intake
from .jira_scope import parse_allowed_projects, writable_issue

logger = logging.getLogger(__name__)



def resolve_transition(
    available: list[dict[str, Any]],
    *,
    jira_transition: str | None,
    jira_status: str | None,
    status_category: str | None = None,
) -> dict[str, Any] | None:
    wanted_transition = str(jira_transition or "").strip().lower()
    wanted_status = str(jira_status or "").strip().lower()
    for entry in available:
        name = str(entry.get("name") or "").strip().lower()
        to_status = str(((entry.get("to") or {}).get("name")) or "").strip().lower()
        if wanted_transition and name == wanted_transition:
            return entry
        if wanted_status and to_status == wanted_status:
            return entry
    wanted_category = str(status_category or "").strip().lower()
    if wanted_transition or wanted_status or not wanted_category:
        return None
    in_category = [entry for entry in available if _target_category(entry) == wanted_category]
    # None or several in the category is no match, never a guess
    return in_category[0] if len(in_category) == 1 else None


def _target_category(entry: dict[str, Any]) -> str:
    target = entry.get("to") if isinstance(entry.get("to"), dict) else {}
    category = target.get("statusCategory") if isinstance(target.get("statusCategory"), dict) else {}
    return str(category.get("key") or "").strip().lower()


def will_write_jira(item: WorkItem, workflow: WorkItemWorkflowDefinition, sync_preview: dict[str, Any]) -> bool:
    policy = dict(workflow.sync_policy_json or {})
    return (
        str(item.source_type or "") == "jira"
        and executes(policy, item)  # the intake's own sync_mode, else the workflow default (``sync_policy``)
        and bool(sync_preview.get("sync_back"))
        and bool(
            sync_preview.get("transition")
            or sync_preview.get("target_status")
            or sync_preview.get("target_status_category")
            or str(sync_preview.get("comment_template") or "").strip()
            or sync_preview.get("labels")
        )
    )


def jira_write_effects(item: WorkItem, preview: dict[str, Any]) -> list[dict[str, Any]]:
    sync_preview = dict(preview.get("jira_sync_preview") or {})
    effects: list[dict[str, Any]] = []
    transition, target = sync_preview.get("transition"), sync_preview.get("target_status")
    if transition or target:
        effects.append({"kind": "status", "value": target or transition, "transition": transition,
                        "target_status": target})
    template = str(sync_preview.get("comment_template") or "").strip()
    if template:
        effects.append({"kind": "comment", "value": _render_comment(template, item=item, preview=preview)})
    if sync_preview.get("labels"):
        effects.append({"kind": "labels", "value": list(sync_preview["labels"])})
    return effects


async def _add_labels(
    client: httpx.AsyncClient, url: str, headers: dict[str, str], labels: list[str], source_key: str
) -> tuple[list[str], bool]:
    if not labels:
        return [], False
    response = await client.put(
        url, headers=headers, json={"fields": {}, "update": {"labels": [{"add": label} for label in labels]}}
    )
    if response.status_code >= 400:
        logger.warning("jira_state_sync_labels_failed source_key=%s status=%s", source_key, response.status_code)
        return [], True
    return list(labels), False


async def _jira_access(
    item: WorkItem, db: AsyncSession
) -> tuple[str, dict[str, str], bool, frozenset[str] | None, httpx.Auth | None]:
    config, _refused = await work_item_connection_config(db, item, "jira")
    base_url = str(config.get("jira_url") or "").rstrip("/")
    return base_url, auth_headers(JIRA, config), is_jira_cloud(base_url, config), parse_allowed_projects(
        config.get("jira_allowed_projects")
    ), request_auth(JIRA, config)


async def check_offered_transition(db: AsyncSession, *, item: WorkItem, preview: dict[str, Any]) -> None:
    sync_preview = preview["jira_sync_preview"]
    transition, target = sync_preview.get("transition"), sync_preview.get("target_status")
    category = sync_preview.get("target_status_category")
    sync_preview.update(target_status_resolved=bool(target), transition_available=None, offered_transitions=[])
    if not sync_preview.get("will_mutate_jira"):
        return
    base_url, authorization, _cloud, allowed, http_auth = await _jira_access(item, db)
    try:
        # Before any shortcut, so a comment- or label-only write outside the allowlist is blocked too.
        writable_issue(item.source_key, allowed)  # never even a read outside the allowlist
    except HTTPException:
        sync_preview.update(will_mutate_jira=False, blocked_reason="scope_not_allowed")
        return
    if not (transition or target or category):
        return
    sync_preview["target_status_resolved"] = False
    if not base_url or not (authorization or http_auth):
        return
    transport = egress_transport(CONNECTION_JIRA)
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, transport=transport, auth=http_auth) as client:
        listing = await client.get(
            f"{base_url}/rest/api/2/issue/{item.source_key}/transitions",
            headers={**authorization, "Accept": "application/json"},
        )
    if listing.status_code >= 400:
        return
    available = [entry for entry in listing.json().get("transitions") or [] if isinstance(entry, dict)]
    sync_preview["offered_transitions"] = [
        {"name": entry.get("name"), "to": (entry.get("to") or {}).get("name")} for entry in available
    ]
    matched = resolve_transition(available, jira_transition=transition, jira_status=target, status_category=category)
    if matched is None:
        # Jira would refuse the apply before anything is written (409 with these offers).
        sync_preview.update(will_mutate_jira=False, transition_available=False)
        return
    sync_preview["transition_available"] = True
    if (matched.get("to") or {}).get("name"):
        sync_preview["target_status"] = (matched.get("to") or {}).get("name")
        sync_preview["target_status_resolved"] = True


def _render_comment(template: str, *, item: WorkItem, preview: dict[str, Any]) -> str:
    values = {
        "source_key": item.source_key,
        "from_state": str(preview.get("from_state") or ""),
        "to_state": str(preview.get("to_state") or ""),
        "reason": str(preview.get("reason") or ""),
    }
    try:
        return template.format(**values).strip()
    except (KeyError, IndexError, ValueError):
        return template.strip()


async def execute_jira_state_sync(
    db: AsyncSession,
    *,
    item: WorkItem,
    workflow: WorkItemWorkflowDefinition,
    preview: dict[str, Any],
) -> dict[str, Any] | None:
    if str(item.source_type or "") != "jira":
        # Platform-native (and any non-Jira) items never reach Jira, even
        # when the project's workflow runs in execute mode.
        return None
    await load_item_intake(db, item)
    policy = dict(workflow.sync_policy_json or {})
    if not executes(policy, item):  # the intake's own sync_mode, else the workflow default (``sync_policy``)
        return None
    sync_preview = dict(preview.get("jira_sync_preview") or {})
    if not sync_preview.get("sync_back"):
        return None
    jira_transition = sync_preview.get("transition")
    jira_status = sync_preview.get("target_status")
    category = sync_preview.get("target_status_category")
    template = str(sync_preview.get("comment_template") or "").strip()
    labels = [str(label) for label in sync_preview.get("labels") or []]
    # comment-only mapping: the platform state has no Jira status counterpart
    # (e.g. the project's Jira workflow lacks a review status) - the ticket
    # gets the mapped comment (and labels), its status stays untouched.
    comment_only = not jira_transition and not jira_status and not category
    if comment_only and not template and not labels:
        return None

    # The credential of the Jira auth mode (Basic or Bearer), never the other secret.
    base_url, authorization, cloud, allowed, http_auth = await _jira_access(item, db)
    # Re-checked at write time; an item synced before the allowlist was narrowed is not writable.
    writable_issue(item.source_key, allowed)
    if not base_url or not (authorization or http_auth):
        raise HTTPException(
            status_code=422,
            detail="Workflow requests a Jira transition but the project has no Jira credentials configured",
        )
    headers = {
        **authorization,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    # Jira Cloud comments are ADF on v3; Server/DC keeps v2 with the plain wiki text.
    issue_url = f"{base_url}/rest/api/2/issue/{item.source_key}"
    comment_url = f"{base_url}/rest/api/3/issue/{item.source_key}/comment" if cloud else f"{issue_url}/comment"
    update_url = f"{base_url}/rest/api/3/issue/{item.source_key}" if cloud else issue_url
    if comment_only:
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True, transport=egress_transport(CONNECTION_JIRA), auth=http_auth
        ) as client:
            labels_applied, labels_failed = await _add_labels(client, update_url, headers, labels, item.source_key)
            comment_posted = False
            if template:
                comment = await client.post(
                    comment_url,
                    headers=headers,
                    json={"body": rich_text_body(_render_comment(template, item=item, preview=preview), cloud=cloud)},
                )
                if comment.status_code >= 400:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Jira comment-only sync failed ({comment.status_code}) for {item.source_key}",
                    )
                comment_posted = True
        logger.info("jira_state_sync_comment_only source_key=%s to_state=%s", item.source_key, preview.get("to_state"))
        return {"executed": True, "mode": "comment_only", "comment_posted": comment_posted,
                "labels_applied": labels_applied, "labels_failed": labels_failed}
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, transport=egress_transport(CONNECTION_JIRA), auth=http_auth
    ) as client:
        listing = await client.get(f"{issue_url}/transitions", headers=headers)
        if listing.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"Jira transitions lookup failed ({listing.status_code}) for {item.source_key}",
            )
        available = list(listing.json().get("transitions") or [])
        matched = resolve_transition(
            available, jira_transition=jira_transition, jira_status=jira_status, status_category=category
        )
        if matched is None:
            offered = [
                f"{entry.get('name')} -> {((entry.get('to') or {}).get('name'))}" for entry in available
            ]
            wanted = jira_transition or jira_status or f"exactly one transition to status category '{category}'"
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Mapped Jira transition '{wanted}' is not available from the "
                    f"issue's current status. Jira offers: {offered or 'none'}"
                ),
            )
        response = await client.post(
            f"{issue_url}/transitions",
            headers=headers,
            json={"transition": {"id": str(matched.get("id"))}},
        )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"Jira transition failed ({response.status_code}) for {item.source_key}",
            )
        # Labels only after the transition succeeded; a refused label change never undoes it.
        labels_applied, labels_failed = await _add_labels(client, update_url, headers, labels, item.source_key)
        comment_posted = False
        if template:
            comment = await client.post(
                comment_url,
                headers=headers,
                json={"body": rich_text_body(_render_comment(template, item=item, preview=preview), cloud=cloud)},
            )
            comment_posted = comment.status_code < 400
            if not comment_posted:
                logger.warning(
                    "jira_state_sync_comment_failed source_key=%s status=%s",
                    item.source_key,
                    comment.status_code,
                )
    result = {
        "executed": True,
        "transition_id": str(matched.get("id")),
        "transition_name": matched.get("name"),
        "resulting_status": (matched.get("to") or {}).get("name"),
        "comment_posted": comment_posted,
        "labels_applied": labels_applied,
        "labels_failed": labels_failed,
    }
    logger.info(
        "jira_state_sync_executed source_key=%s transition=%s -> %s",
        item.source_key,
        result["transition_name"],
        result["resulting_status"],
    )
    return result


__all__ = [
    "execute_jira_state_sync",
    "jira_write_effects",
    "check_offered_transition",
    "resolve_transition",
    "will_write_jira",
]
