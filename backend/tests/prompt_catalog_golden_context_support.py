"""Fixed inputs for the context-prompt golden scenarios (summarizer, compaction, checkpoint, agent).

``context_outputs`` renders every catalog-backed context surface from these inputs; the pinned digests in
``test_prompt_catalog_golden_context.py`` are of these renders.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

AGENT: dict[str, Any] = {
    "name": "Release Agent",
    "goal": "",
    "description": "Ship the release.",
    "branchPrefix": "rel",
    "systemPrompt": "Prefer small steps {literally}.",
    "outputPrompt": "A table.",
    "steps": [
        {"position": 1, "name": "Inspect", "stepType": "diagnosis", "instructions": "Read.", "successCriteria": "",
         "allowedTools": ["read_file"], "isEnabled": True},
        {"position": 2, "name": "Skip", "stepType": "change", "instructions": "", "successCriteria": "",
         "allowedTools": [], "isEnabled": False},
        {"position": 3, "name": "Change", "stepType": "change", "instructions": "", "successCriteria": "Green.",
         "allowedTools": [], "isEnabled": True},
    ],
}
BARE_AGENT: dict[str, Any] = {"name": "Bare", "goal": "Goal.", "description": "", "steps": []}
EVIDENCE_REFS = [
    {"ref": "msg:1", "role": "user", "excerpt": "Deploy it"},
    {"ref": "tool_call:2", "role": "tool", "tool_name": "get_logs"},
    {"ref": "", "role": "x"},
]
COMPACTION = SimpleNamespace(
    id="c-1",
    compaction_index=2,
    source_message_count=14,
    source_first_message_id="m-1",
    source_last_message_id=None,
    recent_message_count=8,
    summary_text="  Summary text.  ",
    evidence_refs_json=[{"type": "message", "message_id": "m-3", "role": "user"}, {"tool_call_id": "t-1"}],
)
BARE_COMPACTION = SimpleNamespace(
    id="c-2", compaction_index=1, source_message_count=3, source_first_message_id=None,
    source_last_message_id="m-9", recent_message_count=4, summary_text=None, evidence_refs_json=None,
)
CHECKPOINT = SimpleNamespace(checkpoint_name="before-deploy")
HISTORY = [SimpleNamespace(role="user", content=f"message {index}", tool_calls=None) for index in range(12)]
PERSONALITIES = [
    SimpleNamespace(language=language, detail_level=detail, communication_style=style, custom_prompt=custom)
    for language, detail, style, custom in (
        ("de", "minimal", "casual", ""),
        ("en", "detailed", "formal", "Use metric units."),
        ("fr", "verbose", "concise", ""),
        ("fr", "unknown", "unknown", ""),
        ("it", "standard", "technical", None),
    )
]


def personality_outputs(build_personality_prompt: Any) -> dict[str, str]:
    return {f"personality:{index}": build_personality_prompt(item) for index, item in enumerate(PERSONALITIES)}


def context_outputs() -> dict[str, str]:
    from app.agent.core.prompts.prompt_builder import build_personality_prompt
    from app.agent.core.runtime._summarizer_evidence import render_evidence_prompt_block
    from app.agent.core.runtime.summarizer import build_history_messages, build_summary_user_prompt
    from app.services.agent_definition_payload import build_agent_execution_prompt
    from app.services.context_checkpoint.service import render_context_checkpoint_for_prompt
    from app.services.context_compaction import render_context_compaction_for_prompt
    from app.services.prompt_catalog import render_prompt

    def history(summary: Any, references: list | None) -> str:
        injected, _recent = build_history_messages(HISTORY, summary, summary_references=references)
        return "\x00".join(f"{item['role']}:{item['content']}" for item in injected)

    evidence_block = render_evidence_prompt_block(EVIDENCE_REFS)
    return {
        "agent:full": build_agent_execution_prompt(AGENT),
        "agent:bare": build_agent_execution_prompt(BARE_AGENT),
        "evidence_block": evidence_block,
        "evidence_block:empty": render_evidence_prompt_block([]),
        "summarizer:system": render_prompt("context.summarizer.system"),
        "summarizer:user": build_summary_user_prompt(
            existing_summary="Old summary.", messages_text="USER: hi", evidence_block=evidence_block
        ),
        "summarizer:user:first": build_summary_user_prompt(
            existing_summary="", messages_text="USER: hi", evidence_block=""
        ),
        "history:text": history("Summary so far.", None),
        "history:json:refs": history({"goal": "g"}, ["msg:1"]),
        "compaction": render_context_compaction_for_prompt(COMPACTION),
        "compaction:bare": render_context_compaction_for_prompt(BARE_COMPACTION),
        "checkpoint": render_context_checkpoint_for_prompt(CHECKPOINT),
        **personality_outputs(build_personality_prompt),
    }
