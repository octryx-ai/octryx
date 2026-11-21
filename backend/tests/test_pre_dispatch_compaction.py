"""Focused tests for pre-dispatch compaction planning."""

from app.agent.engine.pre_dispatch._pre_dispatch_compaction import _build_pre_dispatch_compaction_plan


def test_pre_dispatch_compaction_plan_skips_when_prompt_is_within_budget() -> None:
    messages = [
        {"role": "system", "content": "system instructions"},
        {"role": "user", "content": "current request"},
    ]

    plan = _build_pre_dispatch_compaction_plan(
        messages=messages,
        runtime={"provider_name": "copilot", "model": "claude-4-sonnet"},
        max_tokens=1024,
    )

    assert plan.should_compact is False
    assert plan.reason == "within_pre_dispatch_budget"
    assert plan.compacted_messages == messages
    assert plan.compacted_prompt_tokens == plan.estimated_prompt_tokens


def test_pre_dispatch_compaction_plan_triggers_earlier_for_fast_models() -> None:
    messages = [
        {"role": "system", "content": "system " * 2400},
        {"role": "user", "content": "old request " * 500},
        {"role": "assistant", "content": "older narrative " * 500},
        {"role": "user", "content": "current request"},
    ]

    fast_plan = _build_pre_dispatch_compaction_plan(
        messages=messages,
        runtime={"provider_name": "copilot", "model": "claude-haiku-4.5"},
        max_tokens=1024,
    )
    premium_plan = _build_pre_dispatch_compaction_plan(
        messages=messages,
        runtime={"provider_name": "copilot", "model": "claude-4-sonnet"},
        max_tokens=1024,
    )

    assert fast_plan.trigger_token_budget < premium_plan.trigger_token_budget
    assert fast_plan.should_compact is True
    assert premium_plan.should_compact is False


def test_pre_dispatch_compaction_plan_returns_trimmed_messages_when_threshold_is_exceeded() -> None:
    messages = [
        {"role": "system", "content": "system " * 1800},
        {"role": "user", "content": "old request " * 500},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-old", "function": {"name": "todo_read", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "call-old", "content": "artifact " * 1000},
        {"role": "assistant", "content": "older narrative " * 700},
        {"role": "user", "content": "current request"},
    ]

    plan = _build_pre_dispatch_compaction_plan(
        messages=messages,
        runtime={"provider_name": "copilot", "model": "claude-haiku-4.5"},
        max_tokens=1024,
    )

    assert plan.should_compact is True
    assert plan.reason == "pre_dispatch_compaction_recommended"
    assert plan.compacted_prompt_tokens < plan.estimated_prompt_tokens
    assert len(plan.compacted_messages) < len(messages)
    assert plan.compacted_messages[0]["role"] == "system"
    assert plan.compacted_messages[-1]["role"] == "user"


def test_pre_dispatch_compaction_plan_tightens_budget_for_high_reasoning_effort() -> None:
    messages = [
        {"role": "system", "content": "system " * 2600},
        {"role": "user", "content": "request " * 400},
    ]

    low_plan = _build_pre_dispatch_compaction_plan(
        messages=messages,
        runtime={"provider_name": "openrouter", "model": "gpt-5.3-codex"},
        max_tokens=1024,
        reasoning_effort="low",
    )
    high_plan = _build_pre_dispatch_compaction_plan(
        messages=messages,
        runtime={"provider_name": "openrouter", "model": "gpt-5.3-codex"},
        max_tokens=1024,
        reasoning_effort="high",
    )

    assert high_plan.trigger_token_budget < low_plan.trigger_token_budget
    assert high_plan.target_token_budget <= low_plan.target_token_budget
    assert high_plan.model_profile.endswith("_high")


def test_pre_dispatch_compaction_preserves_full_topology_diagram_context() -> None:
    topology_payload = (
        '{"tool_name":"aws_topology_snapshot","result":{"diagram_brief":{"mode":"full",'
        '"selected_nodes":['
        + ",".join(f'{{"ref":"n{index}","label":"resource-{index}"}}' for index in range(160))
        + ']}}}'
    )
    messages = [
        {"role": "system", "content": "system " * 1800},
        {"role": "user", "content": "Create a full draw.io AWS topology overview."},
        {"role": "tool", "content": topology_payload},
        {
            "role": "system",
            "content": (
                "Current step: Build Diagram. This is a full-overview topology diagram: draw the broad selected "
                "topology across visible services. Use aws_topology_snapshot diagram_brief as source of truth."
            ),
        },
    ]

    plan = _build_pre_dispatch_compaction_plan(
        messages=messages,
        runtime={"provider_name": "bedrock", "model": "amazon.nova-2-lite-v1:0"},
        max_tokens=4096,
    )

    assert plan.should_compact is False
    assert plan.reason == "within_pre_dispatch_budget"
    assert plan.model_profile == "full_topology_diagram"
    assert plan.trigger_token_budget >= 50_000
