"""Prompt rendering for runtime Engineering Knowledge Pack resolution.

Domain-owned: the agent core consumes this through a plain import; the EKP
workflow schema (stack keys, versions, pack retrieval fields) lives with the
engineering-knowledge service, not in platform-core prompt modules.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.prompt_catalog import render_prompt

from ..content_security.untrusted_fence import fenced_untrusted, new_fence, untrusted_notice
from . import resolve_engineering_runtime_context


async def resolve_engineering_knowledge_runtime_prompt(
    *,
    db: AsyncSession,
    project_id: str | None,
    session_metadata: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """The Engineering Knowledge runtime section from explicit inputs only.

    Sources: a parent run's resolution, the session's bound repository (``code_repository_id``) and
    the repository manifest (source versions). The turn's prompt text is not a parameter; an
    unresolved input is a closed ``needs_clarification`` state, never a default.
    """
    parent_resolution = session_metadata.get("parent_engineering_knowledge_runtime_resolution")
    if isinstance(parent_resolution, dict) and parent_resolution:
        return _render_runtime_prompt(parent_resolution), dict(parent_resolution)

    repository_id = str(
        session_metadata.get("code_repository_id") or session_metadata.get("repository_id") or ""
    ).strip() or None
    resolution = await resolve_engineering_runtime_context(
        db,
        project_id=project_id,
        repository_id=repository_id,
        local_search_roots=_metadata_list(session_metadata.get("engineering_knowledge_repo_search_roots")),
        max_items=6,
        budget_tokens=int(session_metadata.get("engineering_knowledge_budget_tokens") or 6_000),
    )
    if resolution.request.intent == "general":
        return "", {}
    bundle = resolution.context_bundle()
    return _render_runtime_prompt(bundle), _compact_resolution_metadata(bundle)


def _render_runtime_prompt(bundle: dict[str, Any]) -> str:
    prompt_contract = dict(bundle.get("prompt_contract") or {})
    intent = str(prompt_contract.get("intent") or "")

    lines = [
        "## Engineering Knowledge Runtime Context",
        f"Status: {'ready' if not bundle.get('blockers') else 'blocked'} ({bundle.get('state') or 'unknown'})",
        f"Intent: {intent or 'unknown'}",
        f"Stack: {prompt_contract.get('stack_key') or 'unknown'}",
        f"Target versions: {_format_mapping(prompt_contract.get('target_versions'))}",
    ]
    source_versions = prompt_contract.get("source_versions") or {}
    if source_versions:
        lines.append(f"Detected source versions: {_format_mapping(source_versions)}")
    lines.extend(_render_repository(bundle))
    lines.extend(_render_pack(bundle))
    lines.extend(_render_blockers(bundle))
    if _requires_knowledge_build_first(bundle):
        lines.extend(_render_build_first(bundle))
        return "\n".join(lines)
    if bundle.get("blockers"):
        lines.append(render_prompt("knowledge.engineering.runtime.blocked"))
        return "\n".join(lines)

    # Rendered in run preparation, inside the turn's bound prompt set.
    lines.append(render_prompt("knowledge.engineering.runtime.baseline"))
    lines.extend(_render_pack_content(bundle))
    return "\n".join(lines)


def _render_build_first(bundle: dict[str, Any]) -> list[str]:
    build_request = dict(bundle.get("knowledge_build_request") or {})
    tool_arguments = build_request.get("tool_arguments")
    build_arguments = json.dumps(tool_arguments, sort_keys=True) if isinstance(tool_arguments, dict) else ""
    lines = [render_prompt("knowledge.engineering.runtime.build_first")]
    if build_arguments and not build_request.get("requires_source_version_discovery"):
        lines.append(render_prompt("knowledge.engineering.runtime.build_arguments", build_arguments=build_arguments))
    elif build_arguments:
        lines.append(
            render_prompt("knowledge.engineering.runtime.draft_build_arguments", build_arguments=build_arguments)
        )
    lines.append(render_prompt("knowledge.engineering.runtime.continue_after_pack"))
    return lines


def _render_pack_content(bundle: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    # Pack items and facts are text from synced repositories and documents: fenced as untrusted data (security
    # review), one fence for the section; titles, ranks and source keys stay outside.
    fence = new_fence()
    items = list(bundle.get("items") or [])
    pack_retrieval = dict(bundle.get("engineering_pack_retrieval") or {})
    facts = list(pack_retrieval.get("facts") or [])
    if items or facts:
        lines.append(untrusted_notice(fence, "the Engineering Knowledge Pack"))
    for item in items:
        lines.append(
            "- "
            + str(item.get("title") or "Untitled")
            + f" (rank {item.get('retrieval_rank')}, source {item.get('source_key') or 'none'})"
        )
        content = str(item.get("content") or item.get("summary") or "").strip()
        if content:
            lines.append(fenced_untrusted("pack item", content[:1200], fence))
    if facts:
        lines.append("Retrieved Engineering Pack facts:")
        for fact in facts[:8]:
            text = str(fact.get("summary") or fact.get("title") or "")[:500]
            lines.append(
                "- "
                + str(fact.get("fact_id") or fact.get("record_key") or "fact")
                + f" (source {fact.get('source_key') or 'none'}): "
                + fenced_untrusted("pack fact", text, fence)
            )
    sources = list(pack_retrieval.get("sources") or [])
    if sources:
        lines.append("Retrieved Engineering Pack sources:")
        for source in sources[:5]:
            lines.append(
                "- "
                + str(source.get("source_key") or source.get("record_key") or "source")
                + f": {source.get('canonical_uri') or source.get('source_uri') or 'no uri'}"
            )
    return lines


def _requires_knowledge_build_first(bundle: dict[str, Any]) -> bool:
    build_request = dict(bundle.get("knowledge_build_request") or {})
    if build_request.get("required"):
        return True
    codes = {str(item.get("code") or "").strip() for item in (bundle.get("blockers") or []) if isinstance(item, dict)}
    return bool(codes.intersection({"missing_engineering_knowledge_pack", "stale_engineering_knowledge_pack"}))


def _render_repository(bundle: dict[str, Any]) -> list[str]:
    repository = dict(bundle.get("repository") or {})
    if not repository.get("id") and not repository.get("candidates"):
        return []
    if repository.get("id"):
        return [
            f"Repository: {repository.get('name')} ({repository.get('repo_root')})",
            f"Repository match: {repository.get('match_reason')}",
        ]
    candidates = ", ".join(str(candidate.get("name")) for candidate in repository.get("candidates") or [])
    return [f"Repository candidates: {candidates}"]


def _render_pack(bundle: dict[str, Any]) -> list[str]:
    pack = dict(bundle.get("engineering_knowledge_pack") or {})
    if not pack.get("version_id"):
        return []
    retrieval = dict(bundle.get("retrieval") or {})
    return [
        f"Pack: {pack.get('pack_key')} v{pack.get('version')} ({pack.get('quality_status')})",
        f"Pack match: {pack.get('match_reason')}",
        f"Freshness: {_format_mapping(retrieval.get('freshness_status'))}",
        f"Source ids: {', '.join(retrieval.get('source_ids') or []) or 'none'}",
    ]


def _render_blockers(bundle: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    blockers = list(bundle.get("blockers") or [])
    if blockers:
        lines.append("Blockers:")
        lines.extend(f"- {item.get('code')}: {item.get('message')}" for item in blockers)
    questions = list(bundle.get("clarification_questions") or [])
    if questions:
        lines.append("Clarification questions:")
        lines.extend(f"- {question}" for question in questions)
    return lines


def _compact_resolution_metadata(bundle: dict[str, Any]) -> dict[str, Any]:
    compact = dict(bundle)
    compact["items"] = [
        {
            "item_id": item.get("item_id"),
            "title": item.get("title"),
            "source_id": item.get("source_id"),
            "source_key": item.get("source_key"),
            "retrieval_rank": item.get("retrieval_rank"),
        }
        for item in bundle.get("items") or []
    ]
    return compact


def _metadata_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        return [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]
    return []


def _format_mapping(value: Any) -> str:
    mapping = dict(value or {}) if isinstance(value, dict) else {}
    if not mapping:
        return "none"
    return ", ".join(f"{key}={mapping[key]}" for key in sorted(mapping))
