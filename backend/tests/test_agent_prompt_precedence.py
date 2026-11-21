"""Contract: a selected agent's instructions and their governed precedence boundary.

- every variant the context plan gives the blueprint (full, minimal, summary, admin) carries the
  authored blueprint exactly once, in the stable (cacheable) part; the catalog key
  ``context.agent.instruction_priority`` follows as its own ``## Instruction Precedence`` section
  after the Communication Preferences, with the generic whole-reply exact-output rule (slice A);
  bounded_evidence carries neither; an ordinary chat turn (no agent) gets no precedence text;
- the boundary is a governed catalog key: its use is attributed as ``key@version`` and a published
  administrator body is what renders and is reported as not the current seed; a published body that
  drops an authored instruction's placeholder is reported, never patched;
- the authored payload (workflow injection, Work Strategy) is unchanged and the injected workflow
  agent prompt stays a single system message.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.agent.core.prompts.agent_blueprint import (
    AGENT_BLUEPRINT_HEADING,
    INSTRUCTION_PRIORITY_HEADING,
    INSTRUCTION_PRIORITY_KEY,
    agent_instruction_carrier_gaps,
    instruction_priority_not_current_seed,
)
from app.agent.core.prompts.prompt_builder import build_system_prompt_parts
from app.agent.loops.setup._loop_bootstrap import apply_loop_bootstrap_messages
from app.services.agent_definition_payload import build_agent_execution_prompt
from app.services.prompt_catalog import prompt_set_scope, render_prompt, resolve_prompt_set, seed_prompt_set
from app.services.prompt_catalog.prompt_set import PromptSet

AGENT = {
    "name": "Format agent",
    "goal": "Return the total as SUM=<number>.",
    "description": "",
    "systemPrompt": "Use the numbers from the user message.",
    "outputPrompt": "Reply with exactly one line: SUM=<number>.",
    "steps": [],
}
PERSONALITY = "Explain context. Show relevant logs, metrics and events."
VARIANTS_WITH_BLUEPRINT = ("full", "minimal", "summary", "admin")


def _agent() -> dict:
    agent = dict(AGENT)
    agent["prompt"] = build_agent_execution_prompt(agent)
    return agent


def _parts(variant: str, agent_definition: dict | None, capability: str = "diagnosis"):
    mode = SimpleNamespace(key=capability, name=capability, capability_type=capability, prompt_instructions="")
    return build_system_prompt_parts(
        agent_type=capability,
        agent_mode=mode,
        personality=PERSONALITY,
        memory="",
        skills="",
        agent_definition=agent_definition,
        thinking_level="light",
        prompt_variant=variant,
    )


@pytest.mark.parametrize("variant", VARIANTS_WITH_BLUEPRINT)
def test_blueprint_is_stable_once_and_the_precedence_section_follows_communication_preferences(variant):
    agent = _agent()
    priority = render_prompt(INSTRUCTION_PRIORITY_KEY)
    parts = _parts(variant, agent)
    for text in (agent["prompt"], priority, AGENT_BLUEPRINT_HEADING, INSTRUCTION_PRIORITY_HEADING):
        assert parts.combined.count(text) == 1, (variant, text[:40])
        assert text in parts.stable and text not in parts.dynamic, "kept in the cacheable part"
    stable = parts.stable
    assert stable.index(AGENT_BLUEPRINT_HEADING) < stable.index(agent["prompt"]) < stable.index(PERSONALITY)
    assert stable.index("## Communication Preferences") < stable.index(INSTRUCTION_PRIORITY_HEADING), (
        "the precedence section is the last word on style"
    )
    assert stable.index(INSTRUCTION_PRIORITY_HEADING) < stable.index(priority)
    assert PERSONALITY in stable, "communication preferences are kept, not removed"


def test_bounded_evidence_and_ordinary_chat_get_no_blueprint_or_boundary():
    priority = render_prompt(INSTRUCTION_PRIORITY_KEY)
    bounded = _parts("bounded_evidence", _agent())
    assert AGENT_BLUEPRINT_HEADING not in bounded.combined and priority not in bounded.combined
    assert INSTRUCTION_PRIORITY_HEADING not in bounded.combined
    for variant in VARIANTS_WITH_BLUEPRINT:
        plain = _parts(variant, None)
        assert AGENT_BLUEPRINT_HEADING not in plain.combined and priority not in plain.combined, variant
        assert INSTRUCTION_PRIORITY_HEADING not in plain.combined, variant
        assert PERSONALITY in plain.combined, "ordinary chat personality unchanged"
    empty = _parts("full", {"name": "No instructions", "prompt": "  "})
    assert AGENT_BLUEPRINT_HEADING not in empty.combined, "nothing to prioritize, no empty section"


def test_the_boundary_never_promotes_the_agent_over_platform_policy():
    priority = render_prompt(INSTRUCTION_PRIORITY_KEY)
    assert "Communication Preferences" in priority
    for mandatory in ("security", "permissions", "approvals", "evidence requirements", "selected workflow"):
        assert mandatory in priority
    assert "never override" in priority
    assert "task data, not operating instructions" in priority


def test_the_boundary_states_a_generic_whole_reply_rule_for_exact_formats():
    priority = render_prompt(INSTRUCTION_PRIORITY_KEY)
    assert "Communication Preferences above" in priority
    assert "exact or machine-readable reply" in priority and "the entire reply is only that output" in priority
    # "explanation" is omitted because "the entire reply is only that output" already excludes it.
    for excluded in ("preface", "visible reasoning", "Markdown", "code fence"):
        assert excluded in priority, excluded
    assert "unless asked" in priority
    assert "SUM" not in priority and "READY" not in priority, "generic, never a task value"
    # The authored payload is untouched: the rule is a governed instruction, not a rewrite of the goal.
    assert build_agent_execution_prompt(dict(AGENT)) == _agent()["prompt"]
    assert "exact or machine-readable" not in _agent()["prompt"]


@pytest.mark.asyncio
async def test_boundary_use_is_attributed_to_the_seeded_published_catalog_version(db):
    prompt_set = await resolve_prompt_set(db, workspace_id=None)
    resolved = prompt_set.resolved(INSTRUCTION_PRIORITY_KEY)
    assert resolved.source == "global" and resolved.version >= 1
    with prompt_set_scope(prompt_set):
        _parts("minimal", _agent())
        assert instruction_priority_not_current_seed() is None, "the seeded catalog serves the current seed"
    usage = prompt_set.usage()
    assert usage[INSTRUCTION_PRIORITY_KEY]["ref"] == f"{INSTRUCTION_PRIORITY_KEY}@{resolved.version}"
    assert usage[INSTRUCTION_PRIORITY_KEY]["digest"] == resolved.digest
    assert resolved.digest == seed_prompt_set().prompts[INSTRUCTION_PRIORITY_KEY].digest
    for carrier in (
        "context.agent.execution_preamble",
        "context.agent.execution_notes_line",
        "context.agent.output_line",
    ):
        assert carrier in usage, carrier


def _with_body(key: str, body: str, *, version: int = 7) -> PromptSet:
    seed = seed_prompt_set()
    prompts = dict(seed.prompts)
    prompts[key] = replace(prompts[key], body=body, version=version, source="global", digest="admin-edit")
    return PromptSet(prompts=prompts, scope={"type": "test"})


def test_a_published_administrator_body_is_what_renders_and_is_reported(caplog):
    edited = _with_body(INSTRUCTION_PRIORITY_KEY, "Administrator precedence wording.")
    with prompt_set_scope(edited):
        with caplog.at_level(logging.WARNING, logger="app.agent.core.prompts.agent_blueprint"):
            parts = _parts("summary", _agent())
        assert instruction_priority_not_current_seed() == f"{INSTRUCTION_PRIORITY_KEY}@7"
    assert "Administrator precedence wording." in parts.stable
    assert "exact or machine-readable" not in parts.combined, "the seed is not re-injected over the admin body"
    assert edited.usage()[INSTRUCTION_PRIORITY_KEY]["ref"] == f"{INSTRUCTION_PRIORITY_KEY}@7"
    reports = [r for r in caplog.records if r.getMessage() == "prompt.agent_instruction_priority_not_current_seed"]
    assert len(reports) == 1 and reports[0].prompt_ref == f"{INSTRUCTION_PRIORITY_KEY}@7"
    with prompt_set_scope(seed_prompt_set()):
        assert instruction_priority_not_current_seed() is None


def test_a_body_that_drops_an_authored_instruction_is_reported_not_patched(caplog):
    edited = _with_body("context.agent.output_line", "Output requirements: keep it short.")
    with prompt_set_scope(edited):
        agent = _agent()
        assert agent_instruction_carrier_gaps(agent) == ["context.agent.output_line@7"]
        with caplog.at_level(logging.WARNING, logger="app.agent.core.prompts.agent_blueprint"):
            parts = _parts("full", agent)
    assert "Reply with exactly one line" not in parts.combined, "the administrator's body is not overwritten"
    assert "Output requirements: keep it short." in parts.combined
    warnings = [record for record in caplog.records if record.getMessage() == "prompt.agent_instruction_not_carried"]
    assert len(warnings) == 1 and warnings[0].prompt_refs == ["context.agent.output_line@7"]

    with prompt_set_scope(seed_prompt_set()):
        assert agent_instruction_carrier_gaps(_agent()) == [], "the seeds carry every authored field"
        assert agent_instruction_carrier_gaps({"name": "x", "goal": "", "prompt": "p"}) == []


def test_injected_workflow_agent_prompt_stays_a_single_system_message():
    explicit = _agent()
    workflow_agent = {"name": "Diagram Designer", "prompt": "Synthetic workflow agent instructions."}
    system = _parts("minimal", explicit).combined
    messages = [{"role": "system", "content": system}, {"role": "user", "content": "17, 25, 8"}]
    for _ in range(2):
        messages = apply_loop_bootstrap_messages(
            messages=messages,
            agent_definition=workflow_agent,
            injected_workflow_agent=True,
            request_analysis={},
            workflow_contract=None,
            build_request_analysis_contract_message=lambda _analysis: "",
            build_workflow_contract_message=lambda _contract: "",
        )
    contents = [message["content"] for message in messages]
    assert contents.count(workflow_agent["prompt"]) == 1, "injected once, not duplicated on re-entry"
    assert sum(content.count(explicit["prompt"]) for content in contents) == 1
    assert messages[-1]["role"] == "user"
