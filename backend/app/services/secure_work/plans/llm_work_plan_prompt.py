"""Work Plan prompt messages and parsing of the model answer."""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import HTTPException

from ....models import (
    WorkItem,
    WorkItemWorkflowDefinition,
)
from ...content_security.untrusted_fence import untrusted_section
from ...prompt_catalog import render_prompt
from ..jira_values import object_value, string_list
from .acceptance_coverage import (
    normalize_acceptance_criteria,
)

WORK_PLAN_PROMPT_VERSION = "2026-06-22.llm_work_plan.v1"
LLM_WORK_TYPES = {
    "coding_change",
    "configuration_change",
    "analysis",
    "documentation",
    "operations",
    "clarification",
    "coordination",
    "unknown",
}


def _llm_work_plan_messages(
    *,
    item: WorkItem,
    workflow: WorkItemWorkflowDefinition | None,
    payload: dict[str, Any],
    clarification_section: str | None = None,
) -> list[dict[str, str]]:
    evidence = _work_item_evidence_for_prompt(item, workflow=workflow)
    clarification = f"{clarification_section}\n\n" if clarification_section else ""
    return [
        {
            "role": "system",
            "content": render_prompt("secure_work.work_plan.system"),
        },
        {
            "role": "user",
            "content": (
                "Create a structured Octryx Work Plan from this Jira Work Item evidence.\n\n"
                f"Prompt version: {WORK_PLAN_PROMPT_VERSION}\n"
                f"Operator hints: {_compact_json(object_value(payload.get('operator_hints')))}\n\n"
                f"{clarification}"
                "JSON schema to return:\n"
                "{\n"
                '  "plan_type": "coding_change | configuration_change | analysis | documentation | '
                'operations | clarification | coordination | unknown",\n'
                '  "title": "short plan title",\n'
                '  "understood_request": "what the work item asks for, with Jira key",\n'
                '  "affected_repositories": [{"repository_name": "...", "repository_url": "...", '
                '"provider": "bitbucket|github|gitlab|unknown", "scope": "...", '
                '"confidence": "high|medium|low", "evidence": "..."}],\n'
                '  "proposed_branches": [{"repository_name": "...", "branch_name": "...", "reason": "..."}],\n'
                '  "planned_files": [{"repository_name": "...", "paths": ["..."], "confidence": "high|medium|low"}],\n'
                '  "validation_plan": [{"command": "...", "reason": "...", '
                '"source": "jira|repository_profile|llm_inference|manual_required"}],\n'
                '  "acceptance_criteria": [{"id": "AC1", "text": "requirement clause quoted from the work item", '
                '"source": "work_item", "validation_commands": ["exact command text from validation_plan"]}],\n'
                '  "security_risks": [{"severity": "low|medium|high", "risk": "...", "evidence": "..."}],\n'
                '  "required_approvals": [{"type": "work_plan|code_review|operations|security|product", '
                '"required": true, "reason": "..."}],\n'
                '  "expected_prs": [{"repository_name": "...", "target_branch": "...", '
                '"source_branch": "...", "status": "expected|not_required|unknown"}],\n'
                '  "open_questions": ["..."],\n'
                '  "assumptions": ["..."],\n'
                '  "rollback_plan": "...",\n'
                '  "trace_refs": [{"source": "jira", "key": "...", "value": "..."}]\n'
                "}\n\n"
                f"Evidence:\n{untrusted_section('work item evidence', _compact_json(evidence, limit=12000),
                                                source='the Jira work item')}"
            ),
        },
    ]


def _work_item_evidence_for_prompt(
    item: WorkItem,
    *,
    workflow: WorkItemWorkflowDefinition | None,
) -> dict[str, Any]:
    return {
        "source_type": item.source_type,
        "source_instance": item.source_instance,
        "source_key": item.source_key,
        "source_url": item.source_url,
        "source_project_key": item.source_project_key,
        "source_status": item.source_status,
        "work_state": item.work_state,
        "title": item.title,
        "description": item.description,
        "issue_type": item.issue_type,
        "priority": item.priority,
        "assignee": item.assignee,
        "reporter": item.reporter,
        "labels": list(item.labels_json or []),
        "components": list(item.components_json or []),
        "fix_versions": list(item.fix_versions_json or []),
        "sprint": dict(item.sprint_json or {}),
        "board": dict(item.board_json or {}),
        "linked_issues": list(item.linked_issues_json or []),
        "source_fields": _trim_nested(item.source_fields_json or {}, limit=6000),
        "workflow": {"id": workflow.id, "name": workflow.name, "states": workflow.states_json} if workflow else None,
    }


def _parse_llm_work_plan(content: str, *, item: WorkItem) -> dict[str, Any]:
    if not content:
        raise HTTPException(status_code=502, detail="Runtime returned an empty Work Plan response")
    try:
        raw = json.loads(_json_payload(content))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Runtime returned invalid Work Plan JSON: {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise HTTPException(status_code=502, detail="Runtime Work Plan response must be a JSON object")
    plan_type = str(raw.get("plan_type") or "unknown").strip()
    if plan_type not in LLM_WORK_TYPES:
        plan_type = "unknown"
    understood_request = str(raw.get("understood_request") or "").strip()
    if not understood_request:
        understood_request = f"{item.source_key}: {item.title}"
    return {
        "plan_type": plan_type,
        "title": str(raw.get("title") or f"{item.source_key} Work Plan").strip(),
        "understood_request": understood_request,
        "affected_repositories": _objects(raw.get("affected_repositories")),
        "proposed_branches": _objects(raw.get("proposed_branches")),
        "planned_files": _objects(raw.get("planned_files")),
        "validation_plan": _objects(raw.get("validation_plan")) or _default_llm_validation(plan_type),
        "acceptance_criteria": normalize_acceptance_criteria(raw.get("acceptance_criteria")),
        "security_risks": _objects(raw.get("security_risks")),
        "required_approvals": _objects(raw.get("required_approvals")),
        "expected_prs": _objects(raw.get("expected_prs")),
        "open_questions": string_list(raw.get("open_questions")),
        "assumptions": string_list(raw.get("assumptions")) or [
            "Jira remains the source of truth for task status and sprint metadata.",
            "Execution must wait until this Work Plan is reviewed and approved.",
        ],
        "rollback_plan": str(
            raw.get("rollback_plan")
            or "Stop execution, revert created branches or PRs if any, and restore the previous operational state."
        ).strip(),
        "trace_refs": _objects(raw.get("trace_refs")),
    }


def _json_payload(content: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", content, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        return content[start : end + 1].strip()
    return content.strip()


def _objects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, dict)]


def _default_llm_validation(plan_type: str) -> list[dict[str, Any]]:
    if plan_type in {"coding_change", "configuration_change"}:
        return [
            {
                "command": "Repository-specific validation must be selected before execution.",
                "source": "manual_required",
            }
        ]
    return [{"command": "Manual verification of Work Plan outcome required.", "source": "manual_required"}]


def _compact_json(value: Any, *, limit: int = 1000) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...<truncated>"


def _trim_nested(value: Any, *, limit: int) -> Any:
    text = _compact_json(value, limit=limit)
    try:
        return json.loads(text.replace("...<truncated>", ""))
    except json.JSONDecodeError:
        return text
