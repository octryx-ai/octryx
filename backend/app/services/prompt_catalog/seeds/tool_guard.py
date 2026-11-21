"""Seeds of the tool guard and tool-surface prompts: turn tool guard refusals and next steps, stuck-loop
stagnation reasons, the tool working-set summaries, compact tool-result guidance, the current-step
contract, thread-context next actions and the turn tool messages.

The only code copy of these texts; the catalog serves the published version. Structured fact lines
(artifact entries, fact labels) and the 'not allowed in the current step' protocol text stay in code.
The tool-result texts (``tool_guard_results``) belong to the same area and are appended to ``SPECS`` here.
"""

from __future__ import annotations

from ..contract import RISK_HIGH, PromptKeySpec
from .tool_guard_results import SPECS as RESULT_SPECS

AREA = "tool_guard"

SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="tool_guard.coding_prewrite.error",
        area=AREA,
        title="Pre-write guard: refusal",
        seed="Tool '{tool_name}' is blocked for source-code changes until repository intelligence runs first.",
        placeholders=frozenset({"tool_name"}),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="tool_guard.coding_prewrite.reason",
        area=AREA,
        title="Pre-write guard: reason",
        seed=(
            "This turn has not inspected the repository or relevant symbols yet. Analyze the affected area first, then "
            "retry the write."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="tool_guard.clarification.error",
        area=AREA,
        title="Clarification guard: refusal",
        seed="Tool '{tool_name}' is blocked because the coding-run clarification gate is not resolved.",
        placeholders=frozenset({"tool_name"}),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="tool_guard.clarification.reason",
        area=AREA,
        title="Clarification guard: reason",
        seed=(
            "Resolve the persisted clarification questions on the coding-run work item or explicitly record safe "
            "assumptions before editing source-code artifacts."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="tool_guard.technical_source.error",
        area=AREA,
        title="Source credibility guard: refusal",
        seed=(
            "Tool '{tool_name}' is blocked for '{topic}' because '{url}' does not look like an official developer-doc, "
            "API-reference, or support-knowledge source."
        ),
        placeholders=frozenset({"tool_name", "topic", "url"}),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="tool_guard.technical_source.reason",
        area=AREA,
        title="Source credibility guard: reason",
        seed=(
            "For technical research-document workflows, low-credibility blogs and generic marketing pages are not "
            "acceptable evidence. Search again for official documentation, API reference pages, or support articles."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="tool_guard.aws.topology_duplicate_error",
        area=AREA,
        title="AWS topology duplicate guard: refusal",
        seed=(
            "aws_topology_snapshot already returned topology evidence for this turn. Stop collecting duplicate AWS "
            "topology data and synthesize from the previous service_summary."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="tool_guard.aws.topology_duplicate_next_step",
        area=AREA,
        title="AWS topology duplicate guard: next step",
        seed=(
            "Use the previous aws_topology_snapshot result's service_summary. Call the tool again only for services "
            "that were not covered."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="tool_guard.code_structure.error",
        area=AREA,
        title="Code-structure snapshot guard: refusal",
        seed=(
            "Code-structure diagrams render from code_structure_snapshot evidence, and this turn has no snapshot with "
            "parsed classes yet. Fetch the repository into the workspace first (prepare_bitbucket_repository; resolve "
            "the project key via list_bitbucket_repositories if unknown), then call code_structure_snapshot, and only "
            "then create the diagram."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="tool_guard.code_structure.next_step",
        area=AREA,
        title="Code-structure snapshot guard: next step",
        seed=(
            "Call prepare_bitbucket_repository for the requested repository, then code_structure_snapshot (with the "
            "requested languages filter), then create_diagram."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="tool_guard.stuck_loop.repeated_same_target_loop",
        area=AREA,
        title="Stagnation reason: repeated_same_target_loop",
        seed=(
            "Step '{step_name}' is stagnating because it keeps reading the same target via `{target_tool}` without "
            "converging."
        ),
        placeholders=frozenset({"step_name", "target_tool"}),
        description="Stuck-loop detector reason; fed into the loop recovery message as {message}.",
    ),
    PromptKeySpec(
        key="tool_guard.stuck_loop.repetitive_knowledge_lookup_loop",
        area=AREA,
        title="Stagnation reason: repetitive_knowledge_lookup_loop",
        seed=(
            "Step '{step_name}' is stagnating because it keeps cycling through similar Knowledge or Confluence lookups "
            "instead of synthesizing the available evidence."
        ),
        placeholders=frozenset({"step_name"}),
        description="Stuck-loop detector reason; fed into the loop recovery message as {message}.",
    ),
    PromptKeySpec(
        key="tool_guard.stuck_loop.repetitive_evidence_target_cycle",
        area=AREA,
        title="Stagnation reason: repetitive_evidence_target_cycle",
        seed=(
            "Step '{step_name}' is stagnating because it keeps cycling through the same repository evidence targets "
            "instead of changing, validating, or reporting a blocker."
        ),
        placeholders=frozenset({"step_name"}),
        description="Stuck-loop detector reason; fed into the loop recovery message as {message}.",
    ),
    PromptKeySpec(
        key="tool_guard.stuck_loop.repetitive_tool_error_loop",
        area=AREA,
        title="Stagnation reason: repetitive_tool_error_loop",
        seed=(
            "Step '{step_name}' is stagnating because `{repeated_error_tool}` keeps failing with repeated tool errors "
            "instead of producing new evidence."
        ),
        placeholders=frozenset({"repeated_error_tool", "step_name"}),
        description="Stuck-loop detector reason; fed into the loop recovery message as {message}.",
    ),
    PromptKeySpec(
        key="tool_guard.stuck_loop.repetitive_empty_search_loop",
        area=AREA,
        title="Stagnation reason: repetitive_empty_search_loop",
        seed=(
            "Step '{step_name}' is stagnating because `web_search` keeps returning zero results instead of producing "
            "usable evidence."
        ),
        placeholders=frozenset({"step_name"}),
        description="Stuck-loop detector reason; fed into the loop recovery message as {message}.",
    ),
    PromptKeySpec(
        key="tool_guard.stuck_loop.repetitive_tool_loop",
        area=AREA,
        title="Stagnation reason: repetitive_tool_loop",
        seed=(
            "Step '{step_name}' is stagnating because it keeps calling `{repeated_tool}` without converging on a "
            "conclusion."
        ),
        placeholders=frozenset({"repeated_tool", "step_name"}),
        description="Stuck-loop detector reason; fed into the loop recovery message as {message}.",
    ),
    PromptKeySpec(
        key="tool_guard.stuck_loop.repetitive_meta_tool_loop",
        area=AREA,
        title="Stagnation reason: repetitive_meta_tool_loop",
        seed=(
            "Step '{step_name}' is stagnating because it keeps calling `{repeated_tool}` instead of synthesizing the "
            "already retrieved evidence."
        ),
        placeholders=frozenset({"repeated_tool", "step_name"}),
        description="Stuck-loop detector reason; fed into the loop recovery message as {message}.",
    ),
    PromptKeySpec(
        key="tool_guard.stuck_loop.out_of_contract_tool_loop",
        area=AREA,
        title="Stagnation reason: out_of_contract_tool_loop",
        seed="Step '{step_name}' is stagnating because it repeatedly calls tools outside the current step contract.",
        placeholders=frozenset({"step_name"}),
        description="Stuck-loop detector reason; fed into the loop recovery message as {message}.",
    ),
    PromptKeySpec(
        key="tool_guard.stuck_loop.expanding_search_loop",
        area=AREA,
        title="Stagnation reason: expanding_search_loop",
        seed=(
            "Step '{step_name}' is stagnating because repository evidence is already available and the run keeps "
            "expanding Jira searches instead of moving on."
        ),
        placeholders=frozenset({"step_name"}),
        description="Stuck-loop detector reason; fed into the loop recovery message as {message}.",
    ),
    PromptKeySpec(
        key="tool_guard.stuck_loop.repeated_previous_step_summary",
        area=AREA,
        title="Stagnation reason: repeated_previous_step_summary",
        seed=(
            "Step '{step_name}' is stuck because the assistant keeps re-summarizing a previous step instead of "
            "progressing the current one."
        ),
        placeholders=frozenset({"step_name"}),
        description="Stuck-loop detector reason; fed into the loop recovery message as {message}.",
    ),
    PromptKeySpec(
        key="tool_guard.stuck_loop.duplicate_no_tool_response",
        area=AREA,
        title="Stagnation reason: duplicate_no_tool_response",
        seed=(
            "Step '{step_name}' is stuck because the assistant keeps producing the same no-tool response instead of "
            "taking a new action."
        ),
        placeholders=frozenset({"step_name"}),
        description="Stuck-loop detector reason; fed into the loop recovery message as {message}.",
    ),
    PromptKeySpec(
        key="tool_guard.stuck_loop.iteration_ceiling",
        area=AREA,
        title="Stagnation reason: iteration_ceiling",
        seed=(
            "Step '{step_name}' hit its iteration ceiling after {attempts_used} tool attempts (limit "
            "{max_iterations})."
        ),
        placeholders=frozenset({"attempts_used", "max_iterations", "step_name"}),
        description="Stuck-loop detector reason; fed into the loop recovery message as {message}.",
    ),
    PromptKeySpec(
        key="tool_guard.step.header",
        area=AREA,
        title="Current step contract: header",
        seed=(
            "Current step: {position}/{total_steps}\n"
            "Step name: {step_name}\n"
            "Step type: {step_type}\n"
            "Step instructions: {instructions}\n"
            "Step success criteria: {success_criteria}"
        ),
        placeholders=frozenset(
            {
                "instructions",
                "position",
                "step_name",
                "step_type",
                "success_criteria",
                "total_steps",
            }
        ),
        risk=RISK_HIGH,
        description="First lines of the current-step system message; '-' fills an empty field.",
    ),
    PromptKeySpec(
        key="tool_guard.step.branch_prefix",
        area=AREA,
        title="Current step contract: branch prefix",
        seed="Repository branch prefix for this agent: {branch_prefix}/",
        placeholders=frozenset({"branch_prefix"}),
    ),
    PromptKeySpec(
        key="tool_guard.step.allowed_tools",
        area=AREA,
        title="Current step contract: allowed tools",
        seed="Only the following tools are allowed in this step: {tools}",
        placeholders=frozenset({"tools"}),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="tool_guard.step.meta_tools",
        area=AREA,
        title="Current step contract: meta tools",
        seed=(
            "Meta tools `load_tool_artifact` and `release_context` remain available when needed for compacted context "
            "or checkpoint release."
        ),
    ),
    PromptKeySpec(
        key="tool_guard.step.all_tools",
        area=AREA,
        title="Current step contract: all tools allowed",
        seed="All currently registered tools are allowed in this step.",
    ),
    PromptKeySpec(
        key="tool_guard.step.tdd_phase",
        area=AREA,
        title="Current step contract: TDD phase",
        seed="Current TDD phase: {phase_index}/{phase_total} - {phase_title}",
        placeholders=frozenset({"phase_index", "phase_title", "phase_total"}),
    ),
    PromptKeySpec(
        key="tool_guard.step.tdd_instructions",
        area=AREA,
        title="Current step contract: TDD phase instructions",
        seed="TDD phase instructions: {instructions}",
        placeholders=frozenset({"instructions"}),
    ),
    PromptKeySpec(
        key="tool_guard.step.complete",
        area=AREA,
        title="Current step contract: completion",
        seed=(
            "Complete this step before moving on. If no more tools are needed for this step, provide a short "
            "completion update."
        ),
    ),
    PromptKeySpec(
        key="tool_guard.thread.next_clarification",
        area=AREA,
        title="Thread context: next action after a question",
        seed="Provide the missing clarification requested by the assistant.",
    ),
    PromptKeySpec(
        key="tool_guard.thread.next_error",
        area=AREA,
        title="Thread context: next action after an error",
        seed="Resolve the latest error or continue from the failed step.",
    ),
    PromptKeySpec(
        key="tool_guard.thread.next_tool_results",
        area=AREA,
        title="Thread context: next action after tool results",
        seed="Continue with the next step based on the latest tool results.",
    ),
    PromptKeySpec(
        key="tool_guard.thread.next_continue",
        area=AREA,
        title="Thread context: next action otherwise",
        seed="Continue the thread from the latest assistant response.",
    ),
    PromptKeySpec(
        key="tool_guard.turn.duplicate_read_only",
        area=AREA,
        title="Duplicate read-only call skipped",
        seed=(
            "This exact read-only tool call already succeeded earlier in the turn. The compact prior evidence is "
            "repeated here so you can continue to the next distinct step."
        ),
    ),
    PromptKeySpec(
        key="tool_guard.turn.diagram_stop_title",
        area=AREA,
        title="All evidence diagrams rendered",
        seed="All evidence diagrams already rendered - stop drawing",
        risk=RISK_HIGH,
        description="Title of the empty create_diagram call that replaces a duplicate freehand diagram.",
    ),
    PromptKeySpec(
        key="tool_guard.turn.checkpoint_frozen",
        area=AREA,
        title="Checkpoint guard: context frozen",
        seed=(
            "Context is frozen under checkpoint '{checkpoint_name}'. Call `release_context` before making further tool "
            "calls."
        ),
        placeholders=frozenset({"checkpoint_name"}),
        risk=RISK_HIGH,
    ),
) + RESULT_SPECS
