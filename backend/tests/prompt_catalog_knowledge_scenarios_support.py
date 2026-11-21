"""Fixed inputs of the knowledge-area prompt scenarios and their rendering through the current code.

``tests/prompt_catalog_golden_keys_knowledge.py`` pins ``SCENARIOS``: the SHA-256 of the output for exactly these
inputs (constants, builders and the inline f-strings of the background jobs).
"""

from __future__ import annotations

from hashlib import sha256
from types import SimpleNamespace
from typing import Any

from app.services.knowledge.research import research_steps

SOURCES = [("Spring Boot 4.0 Release Notes", "https://docs.spring.io/rn")]
MEMBERS = [
    SimpleNamespace(id="n1", display_name="Billing", node_type="service", description="Charges cards"),
    SimpleNamespace(id="n2", display_name="Alice", node_type="person", description=None),
]
EDGES = [
    SimpleNamespace(source_node_id="n1", target_node_id="n2", edge_type="owned_by"),
    SimpleNamespace(source_node_id="n1", target_node_id="nx", edge_type="calls"),
]
ONTOLOGY = {"entity_types": ["service", "person"], "relation_types": ["owned_by"]}
BUILD_FIRST = {
    "state": "missing_pack",
    "blockers": [{"code": "missing_engineering_knowledge_pack", "message": "No pack."}],
    "prompt_contract": {"intent": "coding_migration", "stack_key": "java-spring", "target_versions": {"java": "25"}},
    "knowledge_build_request": {"required": True, "tool_arguments": {"stack_key": "java-spring"}},
}
DISCOVERY = {**BUILD_FIRST, "knowledge_build_request": {**BUILD_FIRST["knowledge_build_request"],
                                                        "requires_source_version_discovery": True}}
BLOCKED = {"state": "blocked", "blockers": [{"code": "missing_target_versions", "message": "Ask."}],
           "prompt_contract": {"intent": "coding_migration"}}
READY = {
    "state": "ready",
    "blockers": [],
    "prompt_contract": {"intent": "coding_migration", "stack_key": "java-spring", "target_versions": {"java": "25"},
                        "source_versions": {"java": "21"}},
    "items": [{"title": "Baseline", "retrieval_rank": 1, "source_key": "s1", "content": "Use Java 25.\nNow."}],
}
README_TARGET = {"label": "core", "directory_path": "core", "readme_path": "core/README.md", "issues": ["missing"]}


def pinned_fence():
    """The untrusted-data fence (``content_security/untrusted_fence.py``) draws a random token per prompt;
    pinned here so a rendered prompt has one digest."""
    from unittest import mock

    return mock.patch("app.services.content_security.untrusted_fence.secrets.token_hex",
                      lambda nbytes=8: "f" * (2 * nbytes))


def knowledge_outputs() -> dict[str, str]:
    from app.services.engineering_knowledge.runtime_prompt_renderer import _render_runtime_prompt
    from app.services.knowledge.episodes import turn_capture
    from app.services.knowledge.memory import auto_capture
    from app.services.knowledge_graph.communities import build_report_prompt
    from app.services.knowledge_graph.extractors.prose import build_extraction_prompt, build_gleaning_prompt
    from app.services.knowledge_graph.query_keywords import build_keywords_prompt
    from app.services.prompt_catalog import render_prompt
    from app.services.prompt_catalog.registry import prompt_key_spec

    return {
        "episode:system": render_prompt("knowledge.episode.system", answer_contract=turn_capture.EPISODE_ANSWER_CONTRACT),
        "episode:turn": turn_capture._turn_prompt("Old.", "Why?", "Because.", SOURCES),
        "episode:turn:empty": turn_capture._turn_prompt("", "", "A.", []),
        "memory:system": render_prompt(
            "knowledge.memory.capture_system", answer_contract=auto_capture.MEMORY_ANSWER_CONTRACT
        ),
        "memory:turn": auto_capture._turn_prompt("I prefer tabs.", "Noted."),
        "memory:turn:empty": auto_capture._turn_prompt("I prefer tabs.", ""),
        "memory:notice": render_prompt("knowledge.memory.notice"),
        "package:plan": render_prompt("knowledge.package.plan_system", answer_contract=research_steps.PLAN_ANSWER_CONTRACT),
        "package:select": render_prompt(
            "knowledge.package.select_system", roles=", ".join(research_steps.ROLES),
            answer_contract=research_steps.SELECT_ANSWER_CONTRACT,
        ),
        "graph:report": build_report_prompt(MEMBERS, EDGES),
        "graph:global": render_prompt("knowledge.graph.global_answer", query="What runs billing?", report_lines="[1] R"),
        "graph:extraction": build_extraction_prompt("  Billing is owned by Alice.  ", ONTOLOGY),
        "graph:gleaning": build_gleaning_prompt("Text.", ONTOLOGY, ["Billing"]),
        "graph:gleaning:none": build_gleaning_prompt("Text.", ONTOLOGY, []),
        "graph:keywords": build_keywords_prompt("  Who owns billing?  "),
        "graph:resummarize": render_prompt("knowledge.graph.resummarize", display_name="Billing", description="a. b."),
        "mcp:instructions": prompt_key_spec("knowledge.mcp.instructions").seed,
        "engineering:build_first": _render_runtime_prompt(BUILD_FIRST),
        "engineering:discovery": _render_runtime_prompt(DISCOVERY),
        "engineering:blocked": _render_runtime_prompt(BLOCKED),
        "engineering:ready": _render_runtime_prompt(READY),
        "teams:call": render_prompt("knowledge.teams.call_default_system"),
        "teams:summary": render_prompt("knowledge.teams.meeting_summary_system"),
        "teams:request": render_prompt("knowledge.teams.meeting_summary_request"),
        "readme:system": render_prompt("knowledge.readme.worker_system"),
        "readme:task": render_prompt(
            "knowledge.readme.worker_task", ticket_id="RIVER-1", summary="-", repo_path="/r",
            directory_path="core", readme_path="core/README.md", issues="missing", scope_context="CTX",
        ),
    }


def knowledge_digests() -> dict[str, Any]:
    with pinned_fence():
        outputs = knowledge_outputs()
    return {name: sha256(text.encode("utf-8")).hexdigest() for name, text in outputs.items()}
