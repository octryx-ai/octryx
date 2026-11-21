from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import SessionEntity

SUPPORTED_ENTITY_TYPES = {
    "jira_ticket",
    "k8s_pod",
    "k8s_deployment",
    "git_commit",
    "git_branch",
    "confluence_page",
    "grafana_alert",
    "prometheus_metric",
    "user",
    "service",
}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _merge_state(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing or {})
    for key, value in (incoming or {}).items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged


def _base_entity(
    entity_type: str,
    entity_id: str,
    label: str,
    state_json: dict[str, Any],
    relevance: float,
) -> dict[str, Any]:
    normalized_type = _normalize_text(entity_type)
    if normalized_type not in SUPPORTED_ENTITY_TYPES:
        raise ValueError(f"Unsupported entity_type: {normalized_type}")
    normalized_id = _normalize_text(entity_id)
    if not normalized_id:
        raise ValueError("entity_id is required")
    normalized_label = _normalize_text(label) or normalized_id
    return {
        "entity_type": normalized_type,
        "entity_id": normalized_id,
        "label": normalized_label,
        "state_json": dict(state_json or {}),
        "relevance_score": float(relevance or 1.0),
    }


def _extract_jira_entities(result: dict[str, Any]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for ticket in result.get("results") or []:
        key = _normalize_text(ticket.get("key") or ticket.get("id"))
        if not key:
            continue
        status = ticket.get("status")
        assignee = ticket.get("assignee")
        entities.append(
            _base_entity(
                "jira_ticket",
                key,
                key,
                {
                    "summary": ticket.get("summary"),
                    "status": status.get("name") if isinstance(status, dict) else status,
                    "assignee": assignee.get("displayName") if isinstance(assignee, dict) else assignee,
                    "priority": (ticket.get("priority") or {}).get("name")
                    if isinstance(ticket.get("priority"), dict)
                    else ticket.get("priority"),
                },
                relevance=3.0,
            )
        )
    return entities


def _extract_k8s_entities(result: dict[str, Any]) -> list[dict[str, Any]]:
    command = " ".join(str(part) for part in (result.get("command") or []))
    stdout = _normalize_text(result.get("stdout"))
    if not stdout:
        return []
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []

    entities: list[dict[str, Any]] = []
    if " pods" in f" {command} " or command.endswith("pods") or "get pods" in command:
        for item in items:
            metadata = item.get("metadata") or {}
            status = item.get("status") or {}
            namespace = _normalize_text(metadata.get("namespace") or "default")
            name = _normalize_text(metadata.get("name"))
            if not name:
                continue
            phase = _normalize_text(status.get("phase"))
            reason = ""
            restart_count = 0
            for container in status.get("containerStatuses") or []:
                restart_count = max(restart_count, int(container.get("restartCount") or 0))
                state = container.get("state") or {}
                waiting = state.get("waiting") or {}
                terminated = state.get("terminated") or {}
                reason = _normalize_text(waiting.get("reason") or terminated.get("reason") or reason)
            entities.append(
                _base_entity(
                    "k8s_pod",
                    f"{namespace}/{name}",
                    name,
                    {
                        "namespace": namespace,
                        "phase": phase,
                        "reason": reason,
                        "restart_count": restart_count,
                    },
                    relevance=2.0 if reason or phase in {"Failed", "Unknown"} else 1.2,
                )
            )
        return entities

    if " deployments" in f" {command} " or command.endswith("deployments") or "get deployment" in command:
        for item in items:
            metadata = item.get("metadata") or {}
            spec = item.get("spec") or {}
            status = item.get("status") or {}
            namespace = _normalize_text(metadata.get("namespace") or "default")
            name = _normalize_text(metadata.get("name"))
            if not name:
                continue
            entities.append(
                _base_entity(
                    "k8s_deployment",
                    f"{namespace}/{name}",
                    name,
                    {
                        "namespace": namespace,
                        "replicas": spec.get("replicas"),
                        "ready_replicas": status.get("readyReplicas"),
                        "updated_replicas": status.get("updatedReplicas"),
                        "available_replicas": status.get("availableReplicas"),
                    },
                    relevance=2.0,
                )
            )
        return entities
    return []


def _extract_git_entities(tool_name: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    branch_name = _normalize_text(result.get("branch_name"))
    repo_slug = _normalize_text(result.get("repo_slug"))
    project_key = _normalize_text(result.get("project_key"))
    repo_label = "/".join(part for part in (project_key, repo_slug) if part)

    if tool_name in {"prepare_bitbucket_repository", "commit_and_push_repository_branch"} and branch_name:
        branch_id = f"{repo_label}:{branch_name}" if repo_label else branch_name
        entities.append(
            _base_entity(
                "git_branch",
                branch_id,
                branch_name,
                {
                    "repository": repo_label or None,
                    "local_path": result.get("local_path"),
                    "relative_path": result.get("relative_path"),
                    "base_branch": result.get("base_branch"),
                },
                relevance=2.0,
            )
        )

    commit_hash = _normalize_text(result.get("commit_hash") or result.get("hash"))
    if commit_hash:
        entities.append(
            _base_entity(
                "git_commit",
                commit_hash,
                commit_hash[:12],
                {
                    "branch_name": branch_name or None,
                    "repository": repo_label or None,
                    "message": result.get("message"),
                },
                relevance=1.8,
            )
        )

    if tool_name == "list_recent_bitbucket_commits":
        for repo in result.get("repositories") or []:
            repo_label = _normalize_text(repo.get("label") or "")
            for commit in repo.get("commits") or []:
                display_id = _normalize_text(commit.get("display_id"))
                if not display_id:
                    continue
                entities.append(
                    _base_entity(
                        "git_commit",
                        display_id,
                        display_id,
                        {
                            "repository": repo_label,
                            "message": commit.get("message"),
                            "author_name": commit.get("author_name"),
                            "author_timestamp": commit.get("author_timestamp"),
                        },
                        relevance=1.2,
                    )
                )
    return entities


def _extract_grafana_entities(result: dict[str, Any]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for alert in result.get("active") or []:
        labels = alert.get("labels") or {}
        alert_name = _normalize_text(labels.get("alertname"))
        if not alert_name:
            continue
        status = alert.get("status") or {}
        entities.append(
            _base_entity(
                "grafana_alert",
                alert_name,
                alert_name,
                {
                    "state": status.get("state") or alert.get("state"),
                    "severity": labels.get("severity"),
                    "service": labels.get("service") or labels.get("job"),
                    "summary": (alert.get("annotations") or {}).get("summary"),
                },
                relevance=2.5,
            )
        )
    return entities


def _extract_confluence_entities(result: dict[str, Any]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for page in result.get("pages") or result.get("results") or []:
        page_id = _normalize_text(page.get("id") or page.get("page_id"))
        title = _normalize_text(page.get("title"))
        if not page_id and not title:
            continue
        entities.append(
            _base_entity(
                "confluence_page",
                page_id or title,
                title or page_id,
                {
                    "space_key": page.get("space_key") or page.get("space"),
                    "status": page.get("status"),
                    "url": page.get("url"),
                    "version": page.get("version"),
                },
                relevance=1.5,
            )
        )
    return entities


def _extract_entities_from_text(result: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = "\n".join(
        _normalize_text(result.get(field))
        for field in ("stdout", "stderr", "content", "summary", "message")
        if _normalize_text(result.get(field))
    )
    if not candidates:
        return []
    entities: list[dict[str, Any]] = []
    for match in sorted(set(re.findall(r"\b[A-Z][A-Z0-9]+-\d+\b", candidates))):
        entities.append(_base_entity("jira_ticket", match, match, {}, relevance=1.0))
    for match in sorted(set(re.findall(r"\bfix/[A-Za-z0-9._/-]+\b", candidates))):
        entities.append(_base_entity("git_branch", match, match, {}, relevance=0.8))
    return entities


def extract_session_entities_from_tool_result(tool_name: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(result, dict) or "error" in result:
        return []
    extracted: list[dict[str, Any]] = []
    if tool_name in {"search_jira_tickets", "get_jira_ticket", "get_jira_ticket_details"}:
        extracted.extend(_extract_jira_entities(result))
    if tool_name == "run_kubectl":
        extracted.extend(_extract_k8s_entities(result))
    if tool_name in {
        "prepare_bitbucket_repository",
        "commit_and_push_repository_branch",
        "list_recent_bitbucket_commits",
    }:
        extracted.extend(_extract_git_entities(tool_name, result))
    if tool_name in {"list_grafana_alerts"}:
        extracted.extend(_extract_grafana_entities(result))
    if tool_name == "search_confluence":
        extracted.extend(_extract_confluence_entities(result))
    extracted.extend(_extract_entities_from_text(result))

    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for entity in extracted:
        key = (entity["entity_type"], entity["entity_id"])
        if key not in unique:
            unique[key] = entity
            continue
        unique[key]["state_json"] = _merge_state(unique[key]["state_json"], entity["state_json"])
        unique[key]["relevance_score"] = max(
            float(unique[key]["relevance_score"]),
            float(entity["relevance_score"]),
        )
    return list(unique.values())


def serialize_session_entity(row: SessionEntity) -> dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "label": row.label,
        "state_json": dict(row.state_json or {}) if isinstance(row.state_json, dict) else {},
        "first_seen_message_id": row.first_seen_message_id,
        "last_updated_message_id": row.last_updated_message_id,
        "relevance_score": float(row.relevance_score or 0.0),
        "times_seen": int(row.times_seen or 0),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def upsert_session_entities_from_tool_result(
    db: AsyncSession,
    *,
    session_id: str,
    message_id: str | None,
    tool_name: str,
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    entities = extract_session_entities_from_tool_result(tool_name, result)
    persisted: list[dict[str, Any]] = []
    for entity in entities:
        row = (
            await db.execute(
                select(SessionEntity).where(
                    SessionEntity.session_id == session_id,
                    SessionEntity.entity_type == entity["entity_type"],
                    SessionEntity.entity_id == entity["entity_id"],
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = SessionEntity(
                id=str(uuid.uuid4()),
                session_id=session_id,
                entity_type=entity["entity_type"],
                entity_id=entity["entity_id"],
                label=entity["label"],
                state_json=entity["state_json"],
                first_seen_message_id=message_id,
                last_updated_message_id=message_id,
                relevance_score=float(entity["relevance_score"]),
                times_seen=1,
            )
            db.add(row)
        else:
            row.label = entity["label"] or row.label
            row.state_json = _merge_state(
                dict(row.state_json or {}) if isinstance(row.state_json, dict) else {},
                entity["state_json"],
            )
            row.last_updated_message_id = message_id or row.last_updated_message_id
            row.times_seen = int(row.times_seen or 0) + 1
            row.relevance_score = max(float(row.relevance_score or 0.0), float(entity["relevance_score"])) + 0.2
        persisted.append(serialize_session_entity(row))
    await db.flush()
    return persisted


async def list_session_entities(
    db: AsyncSession,
    *,
    session_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(SessionEntity)
                .where(SessionEntity.session_id == session_id)
                .order_by(desc(SessionEntity.relevance_score), desc(SessionEntity.updated_at))
                .limit(max(1, min(int(limit or 20), 100)))
            )
        )
        .scalars()
        .all()
    )
    return [serialize_session_entity(row) for row in rows]


def render_session_entities_for_prompt(entities: list[dict[str, Any]]) -> str:
    if not entities:
        return ""
    lines: list[str] = []
    for entity in entities:
        state_json = entity.get("state_json") or {}
        state_parts = []
        prompt_relevance = float(entity.get("prompt_relevance_score", 0.0) or 0.0)
        for key in (
            "status",
            "phase",
            "reason",
            "branch_name",
            "summary",
            "assignee",
            "namespace",
            "service",
            "repository",
            "ready_replicas",
        ):
            value = _normalize_text(state_json.get(key))
            if value:
                state_parts.append(f"{key}={value}")
        if prompt_relevance > 0:
            state_parts.append(f"relevance={prompt_relevance:.2f}")
        suffix = f" ({', '.join(state_parts[:4])})" if state_parts else ""
        lines.append(f"- [{entity.get('entity_type')}] {entity.get('label') or entity.get('entity_id')}{suffix}")
    return "\n".join(lines)
