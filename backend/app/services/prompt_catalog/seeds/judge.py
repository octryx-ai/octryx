"""Seeds of the judge and model-side planner prompts: the routing condition operator, the command security analyzer, the
trace-only tool planner and the orchestrator reviewer."""

from __future__ import annotations

from ..contract import RISK_HIGH, PromptKeySpec

AREA = "judge"

SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="judge.security.risk",
        area=AREA,
        title="Command security analyzer prompt",
        seed=(
            "You are an enterprise command security analyzer.\n"
            "{answer_contract}\n"
            "Score for mutation risk, credential exposure, infrastructure impact, and blast radius.\n"
            "Be conservative for production, kubectl, terraform, docker, secret, env, or credential access.\n"
            "\n"
            "Tool: {tool_name}\n"
            "Capability: {capability}\n"
            "Project: {project_label}\n"
            "Command: {command_text}\n"
        ),
        placeholders=frozenset({"answer_contract", "capability", "command_text", "project_label", "tool_name"}),
        risk=RISK_HIGH,
        description="{answer_contract} lists the JSON keys and enums the analyzer parses.",
    ),
    PromptKeySpec(
        key="judge.review.task",
        area=AREA,
        title="Orchestrator reviewer task",
        seed=(
            "Review the following output against criteria: {review_criteria}\n"
            "\n"
            "Output:\n"
            "{output_to_review}\n"
            "\n"
            "Respond with a score: pass/fail (reviewer_critic) or a numeric score + pass/fail (evaluator_optimizer)."
        ),
        placeholders=frozenset({"output_to_review", "review_criteria"}),
        description="System message of the orchestrator's reviewer session.",
    ),
    # The review node runs as the platform Reviewer agent, whose instructions hold its
    # review text (services/platform_agents/seeds.py).
)
