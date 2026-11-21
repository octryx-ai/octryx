"""Tool definitions for engineering knowledge packs and pack drafts."""

from __future__ import annotations

KNOWLEDGE_PACK_DEFINITIONS: dict[str, dict] = {
    "engineering_pack_search": {
        "type": "function",
        "function": {
            "name": "engineering_pack_search",
            "description": (
                "Search Engineering Knowledge Packs by stack, exact source/target versions, topic, artifact, "
                "trust tier, status, and quality status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "stack_key": {"type": "string"},
                    "source_versions": {"type": "object"},
                    "target_versions": {"type": "object"},
                    "topic": {"type": "string"},
                    "artifact": {"type": "string"},
                    "trust_tier": {"type": "string"},
                    "status": {"type": "string"},
                    "quality_status": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "engineering_pack_retrieve": {
        "type": "function",
        "function": {
            "name": "engineering_pack_retrieve",
            "description": (
                "Search active published Engineering Pack retrieval records at pack, item, evidence-fact, "
                "and source level with bounded citation-ready results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search text, e.g. 'JEP 503', 'removed APIs', or 'Key Derivation Function API'.",
                    },
                    "stack_key": {"type": "string"},
                    "source_versions": {"type": "object"},
                    "target_versions": {"type": "object"},
                    "record_kind": {
                        "type": "string",
                        "description": "Optional record kind filter: pack, item, fact, or source.",
                    },
                    "coverage_area": {
                        "type": "string",
                        "description": "Optional coverage area filter such as migration, features, removals_deprecations, build_tooling, runtime_performance, or security_native.",
                    },
                    "trust_tier": {"type": "string"},
                    "source_type": {"type": "string"},
                    "freshness_status": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "engineering_pack_get": {
        "type": "function",
        "function": {
            "name": "engineering_pack_get",
            "description": (
                "Load bounded Engineering Knowledge Pack details, source evidence, and items. "
                "pack_key accepts exact keys and simple target aliases such as 'java-25'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pack_key": {
                        "type": "string",
                        "description": "Exact pack key, pack id, or simple target alias such as 'java-25'.",
                    },
                    "pack_version_id": {"type": "string"},
                    "include_items": {"type": "boolean"},
                    "include_sources": {"type": "boolean"},
                    "max_items": {"type": "integer"},
                },
            },
        },
    },
    "engineering_pack_resolve_for_task": {
        "type": "function",
        "function": {
            "name": "engineering_pack_resolve_for_task",
            "description": (
                "Resolve published Engineering Pack context for an exact migration target. "
                "Pass the stack and the exact target versions; they are not read from prompt text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "stack_key": {
                        "type": "string",
                        "description": "Stack identifier, e.g. 'java-spring', 'java', 'python'.",
                    },
                    "target_versions": {
                        "type": "object",
                        "description": "Exact target versions, e.g. {'java': '25', 'spring_boot': '4.0.3'}.",
                    },
                    "source_versions": {"type": "object"},
                    "max_items": {"type": "integer"},
                },
                "required": ["stack_key", "target_versions"],
            },
        },
    },
    "pack_draft_create": {
        "type": "function",
        "function": {
            "name": "pack_draft_create",
            "description": (
                "Create or reuse an Engineering Knowledge Pack draft. Call this after deciding what stack and "
                "versions to cover. Returns pack_key and pack_version_id for subsequent pack_draft_add_item calls."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pack_name": {"type": "string", "description": "Human-readable pack name."},
                    "stack_key": {
                        "type": "string",
                        "description": "Stack identifier, e.g. 'java-spring', 'java', 'python'.",
                    },
                    "description": {"type": "string"},
                    "source_versions": {
                        "type": "object",
                        "description": 'Current/source versions, e.g. {"java": "21", "spring_boot": "3.4"}.',
                    },
                    "target_versions": {
                        "type": "object",
                        "description": 'Target versions, e.g. {"java": "25", "spring_boot": "4.0"}.',
                    },
                    "research_sources": {
                        "type": "array",
                        "description": (
                            "Evidence sources from your research to register on the draft "
                            "(trust tier is inferred from the domain when omitted). "
                            "Reference their URLs as source_uri in pack_draft_add_item."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string"},
                                "title": {"type": "string"},
                                "trust_tier": {
                                    "type": "string",
                                    "enum": ["official", "vendor", "community"],
                                },
                                "version_label": {"type": "string"},
                            },
                            "required": ["url"],
                        },
                    },
                },
                "required": ["pack_name", "stack_key"],
            },
        },
    },
    "pack_draft_add_item": {
        "type": "function",
        "function": {
            "name": "pack_draft_add_item",
            "description": (
                "Add a knowledge item to an Engineering Knowledge Pack draft. "
                "Write the content yourself from your research — no URL fetching happens here. "
                "Call once per topic (migration step, breaking change, new feature, config key, etc.)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pack_version_id": {"type": "string"},
                    "item_key": {
                        "type": "string",
                        "description": "Unique slug for this item within the pack, e.g. 'java25-virtual-threads'.",
                    },
                    "title": {"type": "string"},
                    "content": {
                        "type": "string",
                        "description": "Full markdown knowledge content from fetched source evidence. Placeholder values such as TODO are rejected.",
                    },
                    "summary": {"type": "string", "description": "One-sentence summary."},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "triggers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Keywords that should trigger retrieval of this item.",
                    },
                    "source_uri": {"type": "string", "description": "Primary source URL for this item."},
                    "trust_tier": {
                        "type": "string",
                        "enum": ["official", "vendor", "community"],
                        "description": "Trust tier of the source.",
                    },
                    "retrieval_priority": {
                        "type": "string",
                        "enum": ["critical", "high", "normal", "low"],
                    },
                    "retrieval_rank": {
                        "type": "integer",
                        "description": "Lower rank = retrieved first. Default 100.",
                    },
                    "version_scope": {
                        "type": "object",
                        "description": 'Version scope, e.g. {"java": "25", "spring_boot": "4.0"}.',
                    },
                },
                "required": ["pack_version_id", "item_key", "title", "content"],
            },
        },
    },
    "pack_draft_finalize": {
        "type": "function",
        "function": {
            "name": "pack_draft_finalize",
            "description": (
                "Finalize an Engineering Knowledge Pack draft: run quality gates and submit for human review "
                "(status → pending_review). The pack is NOT published automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pack_version_id": {"type": "string"},
                    "pack_key": {
                        "type": "string",
                        "description": "Optional exact pack key or simple target alias such as 'java-25'.",
                    },
                    "minimum_items": {
                        "type": "integer",
                        "description": "Minimum reviewable items required before review submission. Default 5.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes for the reviewer explaining the research process.",
                    },
                },
            },
        },
    },
}
