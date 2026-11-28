"""The policy test bench: "may <principal> do <action> on <resource> in <Workspace>?"."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import PolicySetVersion, Project
from ...models.runtime.governed_revision import REVISION_STATE_DRAFT, REVISION_STATE_IN_REVIEW
from ..agent_gateway.policy import load_workspace_policy
from ..agent_gateway.seat_policy import builtin_seat_decision, default_seat_mode
from ..agent_gateway.seat_policy_keys import SEAT_MODE_KEY
from ..agent_gateway.tool_check import DECISION_DENY, evaluate_tool_check
from ..classification_tool_policy import builtin_tool_decision, classification_tool_policy_section
from ..data_classification.policy_matrix import model_allowlists
from ..data_classification.workspace_overrides import workspace_level_rules
from ..knowledge.embedding.selection import REASON_EMBEDDINGS_FORBIDDEN, REASON_RERANKER_FORBIDDEN
from ..model_gateway.data_policy.gate import data_policy_decision
from ..model_gateway.data_policy.source import resolve_workspace_data_classification
from ..model_gateway.litellm.project_admission import build_project_model_admission
from ..prompt_catalog import prompt_set_scope
from ..prompt_catalog.out_of_turn import prompt_set_for
from .bench_question import ERROR_NO_DRAFT, ERROR_WORKSPACE, TOOL_ACTIONS, BenchError, BenchQuestion
from .custom_policies import check_custom_policies
from .engine import compile_policy_set, evaluate
from .gateway_point import gateway_query
from .points import model_query, remote_query, seat_query, tool_query
from .principals import load_principal
from .runtime import published_version
from .schema import (
    ACTION_CALL_MODEL,
    ACTION_RUN_COMMAND,
    ACTION_RUN_ON_DEVICE,
    ACTION_USE_REMOTE_EMBEDDINGS,
    ACTION_USE_RERANKER,
    ACTION_USE_SEAT,
    ID_CLASSIFICATION,
    ID_PLATFORM,
    ID_WORKSPACE,
)

SOURCE_PUBLISHED = "published"
SOURCE_DRAFT = "draft"

@dataclass(frozen=True, slots=True)
class CustomText:
    text: str
    label: str


async def custom_text(db: AsyncSession, source: str | None, policies: str | None = None) -> CustomText:
    if policies is not None:
        return CustomText(check_custom_policies(policies).text, "candidate text")
    if source == SOURCE_DRAFT:
        stmt = (select(PolicySetVersion)
                .where(PolicySetVersion.state.in_([REVISION_STATE_DRAFT, REVISION_STATE_IN_REVIEW]))
                .order_by(PolicySetVersion.version.desc()).limit(1))
        draft = (await db.execute(stmt)).scalar_one_or_none()
        if draft is None:
            raise BenchError(ERROR_NO_DRAFT, 409)
        return CustomText(str(draft.policies_text), f"draft version {draft.version}")
    published = await published_version(db)
    if published is None:
        return CustomText("", "no custom policies published")
    return CustomText(str(published.policies_text), f"published version {published.version}")


def _source(policy_id: str) -> str:
    for prefix, name in ((ID_PLATFORM, "platform"), (ID_CLASSIFICATION, "classification"), (ID_WORKSPACE, "workspace")):
        if policy_id.startswith(prefix):
            return name
    return "custom"


def policy_source_text(text: str, policy_id: str) -> str:
    marker = f'@id("{policy_id}")'
    start = text.find(marker)
    if start < 0:
        return ""
    quoted = escaped = False
    for index in range(start + len(marker), len(text)):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == ";":
            return text[start:index + 1]
    return text[start:]


async def _questions(db: AsyncSession, question: BenchQuestion, project: Project, gateway_principal) -> tuple[Any, Any]:
    principal = gateway_principal
    workspace_id = project.id
    classification = await resolve_workspace_data_classification(db, project_id=workspace_id)
    level = classification.classification if classification.resolved else None
    rules = await workspace_level_rules(db, project.config, level) if level else None
    resource = question.resource
    if question.action == ACTION_USE_SEAT:
        loaded = await load_workspace_policy(db, workspace_id)
        raw = dict(loaded.policy.raw if loaded.policy is not None else {})
        raw.setdefault(SEAT_MODE_KEY, default_seat_mode(level))  # open for public/internal
        legacy = builtin_seat_decision(loaded.policy, rules, level=level) if loaded.policy is not None else None
        query = seat_query(workspace_id=workspace_id, level=level, rules=rules, raw_policy=raw, principal=principal)
        return query, (legacy.allowed, legacy.reason) if legacy is not None else (False, loaded.reason)
    if question.action == ACTION_CALL_MODEL:
        admission = build_project_model_admission(
            project_id=workspace_id, project_config=project.config, source="policy_test_bench",
            data_classification=classification, level_model_aliases=await model_allowlists(db),
        )
        legacy = admission.builtin_decision(resource.get("alias"))
        return model_query(admission, resource.get("alias"), principal=principal), (legacy.allowed, legacy.reason)
    if question.action in (ACTION_USE_RERANKER, ACTION_USE_REMOTE_EMBEDDINGS):
        kind = "reranker" if question.action == ACTION_USE_RERANKER else "embeddings"
        gate = data_policy_decision(classification, resource.get("data_policy_class"))
        rule, refusal = (("reranker_allowed", REASON_RERANKER_FORBIDDEN) if kind == "reranker"
                         else ("remote_embeddings_allowed", REASON_EMBEDDINGS_FORBIDDEN))
        allowed = gate.allowed and rules is not None and bool(getattr(rules, rule))
        reason = gate.reason if not gate.allowed else ("" if allowed else refusal)
        query = remote_query(project_id=workspace_id, classification=classification,
                             data_policy_class=resource.get("data_policy_class"), model_kind=kind,
                             rules=rules if gate.allowed else None, principal=principal)
        return query, (allowed, reason)
    if question.action in TOOL_ACTIONS:
        section = await classification_tool_policy_section(db, project.config, project_id=workspace_id)
        params = resource.get("params")
        legacy = builtin_tool_decision(str(resource["tool"]), section, params)
        query = tool_query(str(resource["tool"]), section, params, principal=principal,
                           connections=resource.get("connections") or ())
        return query, (legacy.allowed, legacy.reason)
    if question.action == ACTION_RUN_ON_DEVICE:
        return await _device_question(db, question, workspace_id, classification, rules, principal)
    loaded = await load_workspace_policy(db, workspace_id)
    if loaded.policy is None:
        raise BenchError("policy_bench_gateway_policy_invalid", 409)
    if question.action == ACTION_RUN_COMMAND:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": resource["command"]}, "cwd": ""}
    else:
        hook_input = {"tool_name": resource["tool"], "tool_input": {"file_path": resource["path"]}, "cwd": ""}
    legacy = evaluate_tool_check(loaded.policy, hook_input)
    query = gateway_query(workspace_id=workspace_id, gateway=loaded.policy, hook_input=hook_input,
                          principal=gateway_principal[0], principal_records=gateway_principal[1],
                          classification=classification)
    return query, (legacy.decision != DECISION_DENY, legacy.rule_id or legacy.reason)


async def _device_question(db: AsyncSession, question: BenchQuestion, workspace_id: str, classification, rules,
                           principal) -> tuple[Any, Any]:
    from types import SimpleNamespace

    from ..devices.device_policy import builtin_device_decision
    from ..devices.device_runs_keys import device_runs_section
    from .device_point import device_query

    loaded = await load_workspace_policy(db, workspace_id)
    raw = loaded.policy.raw if loaded.policy is not None else None
    profile, folder = question.resource["profile"], question.resource["folder_allowlisted"]
    legacy = (builtin_device_decision(device_runs_section(raw), rules, profile=profile, folder_allowlisted=folder)
              if raw is not None else None)
    device = SimpleNamespace(id="bench-device", owner_user_id=principal[0].id, os="linux",
                             profiles=["governed", "seat"], status="active")
    query = device_query(workspace_id=workspace_id, classification=classification, rules=rules, raw_policy=raw,
                         device=device, profile=profile, folder_allowlisted=folder, principal=principal)
    return query, (legacy.allowed, legacy.reason) if legacy is not None else (False, loaded.reason)


async def ask(db: AsyncSession, question: BenchQuestion, custom: CustomText) -> dict[str, Any]:
    project = await db.get(Project, question.workspace_id)
    if project is None or not project.is_active:
        raise BenchError(ERROR_WORKSPACE, 404, "workspace_id")
    principal = await load_principal(db, question.user_id)
    # The existing checks render their refusal texts from the prompt catalog; an admin request has no turn set bound,
    # so they run in the Workspace's set, as the live gateway route does.
    with prompt_set_scope(await prompt_set_for(db, workspace_id=project.id)):
        query, legacy = await _questions(db, question, project, principal)
    notes: list[str] = []
    text = query.policies + ("\n" + custom.text if custom.text else "")
    evaluation = evaluate(compile_policy_set(text), query.requests, query.entities)
    return {
        "decision": "allow" if evaluation.allowed else "deny",
        "action": query.action,
        "principal": query.principal.label(),
        "resource": query.resource,
        "determining": [{"id": policy_id, "source": _source(policy_id), "text": policy_source_text(text, policy_id)}
                        for policy_id in evaluation.determining],
        "errors": list(evaluation.errors),
        "legacy": {"decision": "allow" if legacy[0] else "deny", "reason": legacy[1] or ""} if legacy else None,
        "policy_source": custom.label,
        "notes": notes,
    }


__all__ = [
    "SOURCE_DRAFT",
    "SOURCE_PUBLISHED",
    "CustomText",
    "ask",
    "custom_text",
    "policy_source_text",
]
