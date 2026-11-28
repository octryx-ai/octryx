"""Seeds of the context prompts: summarizer, injected summary, compaction, checkpoint, agent execution."""

from __future__ import annotations

from ..contract import RISK_HIGH, PromptKeySpec

AREA = "context"

SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="context.checkpoint.section",
        area=AREA,
        title="Context checkpoint section",
        seed=(
            "- Active checkpoint: {checkpoint_name}\n"
            "- Context is frozen. Do not call any further tools until you explicitly call `release_context`.\n"
            "- If the work must be abandoned, call `release_context` with action `rollback`."
        ),
        placeholders=frozenset({"checkpoint_name"}),
        risk=RISK_HIGH,
        description="Body of the Context Checkpoint section: no tools until release_context.",
    ),
    PromptKeySpec(
        key="context.agent.execution_preamble",
        area=AREA,
        title="Agent execution prompt: preamble",
        seed=(
            "Selected agent: {agent_name}\n"
            "Goal: {goal}\n"
            "For project or documentation questions, search the governed Knowledge first (knowledge_search); read "
            "only the most relevant pages."
        ),
        placeholders=frozenset({"agent_name", "goal"}),
        risk=RISK_HIGH,
        description="First lines of the Agent Blueprint section of a selected agent definition.",
    ),
    PromptKeySpec(
        key="context.agent.branch_prefix_line",
        area=AREA,
        title="Agent execution prompt: branch prefix",
        seed="Preferred branch prefix for repository change work: `{branch_prefix}/`.",
        placeholders=frozenset({"branch_prefix"}),
    ),
    PromptKeySpec(
        key="context.agent.execution_notes_line",
        area=AREA,
        title="Agent execution prompt: execution notes",
        seed="Execution notes: {system_prompt}",
        placeholders=frozenset({"system_prompt"}),
        description="{system_prompt} is the agent definition's system prompt.",
    ),
    PromptKeySpec(
        key="context.agent.output_line",
        area=AREA,
        title="Agent execution prompt: output requirements",
        seed="Output requirements: {output_prompt}",
        placeholders=frozenset({"output_prompt"}),
        description="{output_prompt} is the agent definition's output prompt.",
    ),
    PromptKeySpec(
        key="context.agent.steps_header",
        area=AREA,
        title="Agent execution prompt: steps header",
        # The step rules ride with the steps: an agent without steps does not carry them.
        seed=(
            "Execute the following ordered steps in order; once a step's evidence meets its success criteria, "
            "continue to the next. A knowledge-update step uses the knowledge tools, never stops at analysis:"
        ),
    ),
    PromptKeySpec(
        key="context.agent.step",
        area=AREA,
        title="Agent execution prompt: one step",
        seed=(
            "{position}. {name} [{step_type}]\n"
            "   Instructions: {instructions}\n"
            "   Success criteria: {success_criteria}\n"
            "   Allowed tools: {allowed_tools}"
        ),
        placeholders=frozenset({"allowed_tools", "instructions", "name", "position", "step_type", "success_criteria"}),
        description="{instructions} and {success_criteria} are '-' when empty.",
    ),
    PromptKeySpec(
        key="context.agent.all_tools_label",
        area=AREA,
        title="Agent execution prompt: no tool restriction",
        seed="all registered tools",
        description="Fills {allowed_tools} when a step allows every registered tool.",
    ),
)
