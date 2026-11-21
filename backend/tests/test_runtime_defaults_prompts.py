"""The runtime mode baseline and the prompt builder: externalized instructions and thinking defaults, section order and cache sections."""

from app.agent.core.prompts.prompt_builder import build_system_prompt, build_system_prompt_parts
from app.agent.runtime_defaults import (
    DEFAULT_AGENT_MODE_KEY,
    DEFAULT_AGENT_MODES,
    get_system_agent_mode_definition,
)
from app.services.agent_mode import normalize_capability_type
from tests.runtime_defaults_support import _Mode

MIGRATED_STATIC_PROMPT_MARKERS = (
    "For project-specific presentation, PowerPoint, deck, or slide requests",
    "For Word, DOCX, report, or business-document generation requests",
    "For Excel, XLSX, workbook, spreadsheet, dashboard",
    "For research-style Word reports",
    "For uploaded PDFs, Office files, images, or research URLs",
    "For Bitbucket requests that ask for recent commits",
    "For repository change tasks",
    "For coding changes in local workspaces",
    "For ANY diagram, flowchart, or architecture request",
    "For Jira time-window queries",
    "When the user asks to configure the platform",
)


def test_runtime_defaults_export_expected_mode_baseline() -> None:
    default_keys = {item["key"] for item in DEFAULT_AGENT_MODES}

    assert DEFAULT_AGENT_MODE_KEY == "diagnosis"
    assert {"diagnosis", "change", "plan", "admin"}.issubset(default_keys)
    assert normalize_capability_type("unsupported") == DEFAULT_AGENT_MODE_KEY


def test_default_agent_mode_prompt_instructions_remain_externalized() -> None:
    mode = _Mode("change", "Change", "change")

    prompt = build_system_prompt(
        agent_type="change",
        agent_mode=mode,
        personality="",
        memory="",
        skills="",
        prompt_variant="minimal",
        thinking_level="deep",
    )

    change_mode = next(item for item in DEFAULT_AGENT_MODES if item["key"] == "change")

    assert change_mode["prompt_instructions"].startswith("Make controlled changes")
    assert "Selected mode: deep" in prompt


def test_system_agent_mode_definition_lookup_uses_governed_registry() -> None:
    change_mode = get_system_agent_mode_definition("change")

    assert change_mode is not None
    assert change_mode.key == "change"
    assert change_mode.capability_type == "change"
    assert change_mode.as_record()["prompt_instructions"].startswith("Make controlled changes")
    assert get_system_agent_mode_definition("missing-mode") is None


def test_prompt_builder_uses_externalized_thinking_defaults_without_prompt_drift() -> None:
    mode = _Mode("diagnosis", "Diagnosis", "diagnosis")

    minimal_prompt = build_system_prompt(
        agent_type="diagnosis",
        agent_mode=mode,
        personality="",
        memory="",
        skills="",
        prompt_variant="minimal",
        thinking_level="off",
    )
    summary_prompt = build_system_prompt(
        agent_type="diagnosis",
        agent_mode=mode,
        personality="",
        memory="",
        skills="",
        prompt_variant="summary",
        thinking_level="deep",
    )
    admin_prompt = build_system_prompt(
        agent_type="admin",
        agent_mode=_Mode("admin", "Admin", "admin"),
        personality="",
        memory="",
        skills="",
        prompt_variant="admin",
        thinking_level="deep",
    )
    full_prompt = build_system_prompt(
        agent_type="diagnosis",
        agent_mode=mode,
        personality="",
        memory="",
        skills="",
        prompt_variant="full",
        thinking_level="deep",
    )

    assert "Selected mode: off" in minimal_prompt
    assert "Instruction: Respond directly." in minimal_prompt
    assert "Selected mode: light" in summary_prompt
    assert "Instruction: Think briefly and synthesize only the relevant deltas." in summary_prompt
    assert "Selected mode: light" in admin_prompt
    assert "inspect the real control-plane state" in admin_prompt
    assert "Selected mode: deep" in full_prompt
    assert "Use deeper reasoning before responding" in full_prompt
    for marker in MIGRATED_STATIC_PROMPT_MARKERS:
        assert marker not in full_prompt
        assert marker not in summary_prompt
        assert marker not in admin_prompt
    assert "instruction_get" in full_prompt
    assert "instruction_get" in summary_prompt
    assert "instruction_get" in admin_prompt
    assert "For ANY diagram, flowchart, or architecture request" not in full_prompt
    assert "For project overview, documentation summary, architecture summary" not in full_prompt
    assert "instruction_get" in full_prompt


def test_prompt_builder_preserves_common_section_order_across_variants() -> None:
    mode = _Mode("diagnosis", "Diagnosis", "diagnosis")

    prompt = build_system_prompt(
        agent_type="diagnosis",
        agent_mode=mode,
        personality="Be concise.",
        memory="Remember repo conventions.",
        skills="Code Search",
        entity_context="session:abc",
        checkpoint_context="latest checkpoint",
        repo_microagents="## Repo Microagents\n### Deploy Agent",
        repo_knowledge="## Repo Knowledge\n### Runbook",
        thinking_level="deep",
    )

    ordered_sections = [
        "## Thinking Mode",
        "## Communication Preferences",
        "## Skill Discovery",
        "## Current Entities",
        "## Context Checkpoint",
        "## Repo Microagents",
        "## Repo Knowledge",
        "## Memory",
    ]

    positions = [prompt.index(section) for section in ordered_sections]
    assert positions == sorted(positions)


def test_prompt_builder_preserves_runtime_environment_section_after_mode_definition() -> None:
    mode = _Mode("diagnosis", "Diagnosis", "diagnosis")

    prompt = build_system_prompt(
        agent_type="diagnosis",
        agent_mode=mode,
        personality="",
        memory="",
        skills="",
        thinking_level="deep",
        system_context={
            "os_name": "macOS",
            "os_release": "14.5",
            "shell": "/bin/zsh",
            "workspace_root": "/tmp/workspace",
            "available_binaries": {"python": "/usr/bin/python3"},
            "command_hints": {"recent_date": "date -v-1d", "notes": "BSD userland"},
        },
    )

    mode_position = prompt.index("## Mode Definition")
    runtime_position = prompt.index("## Runtime Environment")
    thinking_position = prompt.index("## Thinking Mode")

    assert mode_position < thinking_position < runtime_position
    assert "- Available binaries: none detected" not in prompt
    assert "- python: /usr/bin/python3" in prompt
    assert "- Platform note: BSD userland" in prompt


def test_prompt_builder_separates_stable_and_dynamic_cache_sections() -> None:
    mode = _Mode("diagnosis", "Diagnosis", "diagnosis")

    parts = build_system_prompt_parts(
        agent_type="diagnosis",
        agent_mode=mode,
        personality="Respond in English.",
        memory="User-specific memory",
        skills="Use skill_search when useful.",
        entity_context="session entity",
        checkpoint_context="checkpoint",
        repo_knowledge="## Repo Knowledge\nDynamic knowledge",
        thinking_level="deep",
        system_context={"workspace_root": "/tmp/session-workspace"},
        agent_definition={"prompt": "Stable SRE agent contract."},
    )

    assert "## Mode Definition" in parts.stable
    assert "Active behavior:" in parts.stable
    assert "## Thinking Mode" in parts.stable
    assert "Stable SRE agent contract." in parts.stable
    assert "## Communication Preferences" in parts.stable
    assert "## Skill Discovery" in parts.stable
    assert "## Runtime Environment" not in parts.stable
    assert "User-specific memory" not in parts.stable

    assert "## Runtime Environment" in parts.dynamic
    assert "/tmp/session-workspace" in parts.dynamic
    assert "## Current Entities" in parts.dynamic
    assert "## Context Checkpoint" in parts.dynamic
    assert "Dynamic knowledge" in parts.dynamic
    assert "## Memory" in parts.dynamic


def test_prompt_builder_keeps_bounded_evidence_variant_tiny() -> None:
    mode = _Mode("diagnosis", "Diagnosis", "diagnosis")

    parts = build_system_prompt_parts(
        agent_type="diagnosis",
        agent_mode=mode,
        personality="Respond in English.",
        memory="User-specific memory",
        skills="Use skill_search when useful.",
        entity_context="session entity",
        checkpoint_context="checkpoint",
        repo_knowledge="## Repo Knowledge\nDynamic knowledge",
        evidence_grounding="## Evidence-Grounded Answer Contract\nVerbose policy",
        thinking_level="light",
        system_context={"workspace_root": "/tmp/session-workspace"},
        prompt_variant="bounded_evidence",
    )

    # The bounded evidence turn reads exactly the fenced Knowledge results, so it keeps the one fence line; it stays
    # tiny: the base contract plus that line, nothing else, under 400 characters.
    from app.services.prompt_catalog import render_prompt

    assert parts.stable == (
        "Bounded evidence turn. Use only registered tools and only the requested evidence tool. "
        "Answer only from the tool result or a clear denial. Do not guess.\n" + render_prompt("system.untrusted_fence")
    )
    assert len(parts.stable) < 400
    assert parts.dynamic == ""
    assert "## Mode Definition" not in parts.stable
    assert "## Thinking Mode" not in parts.stable
    assert "## Communication Preferences" not in parts.stable
    assert "## Skill Discovery" not in parts.stable
