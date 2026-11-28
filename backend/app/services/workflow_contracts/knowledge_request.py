"""The ``knowledge_request`` family: answer from the governed Workspace evidence only."""

from __future__ import annotations

import re
from typing import Any

from ..turn_tool_history import _build_tool_call, _tool_attempted
from .models import WorkflowDefinition, WorkflowPhase
from .variant import (
    VARIANT_STATE_NEEDS_CONFIGURATION,
    VARIANT_STATE_RESOLVED,
    WORKFLOW_VARIANT_CONTRACT_KEY,
    WorkflowVariant,
)

_ANSWER_INSTRUCTION_PATTERN = re.compile(
    r"\b(?:answer|respond|reply|include|max\.?)\b",
    re.IGNORECASE,
)
_QUESTION_PREFIX_PATTERN = re.compile(
    r"^(?:what is|what can you tell me about|explain)\s+"
    r"(?:the\s+)?",
    re.IGNORECASE,
)
# The answer style of a knowledge lookup is its variant: the selected definition's configured
# contract names it (``knowledge_query_style``); a definition that names none answers as a lookup.
KNOWLEDGE_FAMILY = "knowledge_request"
GOVERNED_EVIDENCE_TOOL = "knowledge_search"
MAX_EVIDENCE_QUERY_CHARS = 500
# Inside the tool's documented 1-20 bound; the tool refuses rather than clamps.
EVIDENCE_RESULT_LIMIT = 8
KNOWLEDGE_QUERY_STYLES = frozenset({"definition", "lookup"})
DEFAULT_KNOWLEDGE_QUERY_STYLE = "lookup"


def match_knowledge_request(
    user_message: str,
    *,
    request_analysis: dict[str, Any] | None = None,
    route_reason: str = "",
    project_id: str | None = None,
    capability_type: str | None = None,
) -> bool:
    del user_message, route_reason, project_id, capability_type
    workflow = (
        (request_analysis or {}).get("workflow_contract")
        if isinstance((request_analysis or {}).get("workflow_contract"), dict)
        else {}
    )
    return str(workflow.get("workflow_id") or "").strip() == "knowledge_request"


def resolve_knowledge_query_style(configured_contract: dict[str, Any] | None) -> WorkflowVariant:
    configured = configured_contract if isinstance(configured_contract, dict) else {}
    style = str(configured.get("knowledge_query_style") or "").strip().lower()
    if not style:
        return WorkflowVariant(
            KNOWLEDGE_FAMILY, VARIANT_STATE_RESOLVED, "no_variant_configured", DEFAULT_KNOWLEDGE_QUERY_STYLE
        )
    if style not in KNOWLEDGE_QUERY_STYLES:
        return WorkflowVariant(KNOWLEDGE_FAMILY, VARIANT_STATE_NEEDS_CONFIGURATION, "unsupported_knowledge_query_style")
    return WorkflowVariant(KNOWLEDGE_FAMILY, VARIANT_STATE_RESOLVED, "knowledge_query_style", style)


def build_knowledge_request_contract(
    user_message: str,
    *,
    request_analysis: dict[str, Any] | None = None,
    route_reason: str = "",
    project_id: str | None = None,
    capability_type: str | None = None,
) -> dict[str, Any]:
    del route_reason, project_id, capability_type
    topic = _knowledge_query_from_message(user_message) or "Project Knowledge"
    configured = (request_analysis or {}).get("workflow_contract")
    variant = resolve_knowledge_query_style(configured if isinstance(configured, dict) else {})
    return {
        "workflow_id": "knowledge_request",
        "workflow_class": "knowledge_request",
        "requires_sources": True,
        "knowledge_query": topic,
        "knowledge_query_style": variant.variant or DEFAULT_KNOWLEDGE_QUERY_STYLE,
        "source_user_message": str(user_message or "").strip(),
        WORKFLOW_VARIANT_CONTRACT_KEY: variant.to_metadata(),
    }


def plan_knowledge_request(
    workflow_contract: dict[str, Any],
    *,
    turn_tool_history: list[dict[str, Any]],
    covered_evidence_axes: set[str] | None,
    allowed_tool_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    del covered_evidence_axes
    query = _knowledge_query_from_message(
        workflow_contract.get("knowledge_query")
        or workflow_contract.get("source_user_message")
        or workflow_contract.get("topic")
        or ""
    )
    if _tool_attempted(turn_tool_history, {GOVERNED_EVIDENCE_TOOL}):
        return []
    return _build_tool_call(
        GOVERNED_EVIDENCE_TOOL,
        {"query": (query or "project knowledge")[:MAX_EVIDENCE_QUERY_CHARS], "limit": EVIDENCE_RESULT_LIMIT},
        allowed_tool_names,
    )


def knowledge_request_definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id=KNOWLEDGE_FAMILY,
        intent_type="knowledge_lookup",
        description="Retrieve source-backed project Knowledge evidence before answering.",
        # Memory recall rides along; the plan still searches the evidence first, and memory is never a source.
        phases=(
            WorkflowPhase(
                "knowledge_search", ("knowledge_search", "knowledge_read", "knowledge_changes", "memory_recall")
            ),
        ),
        matcher=match_knowledge_request,
        contract_builder=build_knowledge_request_contract,
        planner=plan_knowledge_request,
    )


def _knowledge_query_from_message(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    first_question = text.split("?", 1)[0].strip() if "?" in text else text
    instruction_match = _ANSWER_INSTRUCTION_PATTERN.search(first_question)
    if instruction_match:
        first_question = first_question[: instruction_match.start()].strip()
    first_sentence = re.split(r"[\n.;]", first_question, maxsplit=1)[0].strip()
    query = _QUESTION_PREFIX_PATTERN.sub("", first_sentence).strip(" :?!.\"'")
    return query or first_sentence.strip(" :?!.\"'")


__all__ = [
    "DEFAULT_KNOWLEDGE_QUERY_STYLE",
    "KNOWLEDGE_FAMILY",
    "KNOWLEDGE_QUERY_STYLES",
    "build_knowledge_request_contract",
    "knowledge_request_definition",
    "match_knowledge_request",
    "plan_knowledge_request",
    "resolve_knowledge_query_style",
]
