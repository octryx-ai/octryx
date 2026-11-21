"""Seeds of the loop control guards: step contracts, evidence completion, stuck-loop recovery.

Injected by ``agent/loops/outcome``, ``agent/loops/control``, ``agent/core/guards``, the standard
loop runtime and ``services/loop_recovery`` as system messages, tool-result notes or stop answers.
Stop texts are stored without their protocol prefix ``Agent stopped because ``
(``agent/core/guards/stop_text.py``), which session state detection matches.
"""

from __future__ import annotations

from ..contract import RISK_HIGH, PromptKeySpec

AREA = "guard"

SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="guard.evidence.missing_reminder",
        area=AREA,
        title="Evidence contract incomplete: call the named tool next",
        seed=(
            "The workflow/tool evidence contract is not complete yet. Missing evidence: {evidence_label}. Your next "
            "response must be a tool call to `{tool_name}`, not prose and not a permission "
            "question.{prerequisite_text}{guidance_text} Use the user request and prior tool evidence to choose the "
            "arguments, then answer only after this evidence is retrieved or a concrete tool error is available."
        ),
        placeholders=frozenset({"evidence_label", "guidance_text", "prerequisite_text", "tool_name"}),
        risk=RISK_HIGH,
        description=(
            "{prerequisite_text} and {guidance_text} are the optional prerequisite and guidance keys, or empty."
        ),
    ),
    PromptKeySpec(
        key="guard.evidence.prerequisites",
        area=AREA,
        title="Evidence contract: prerequisites already present",
        seed=" Successful prerequisite evidence already exists from: {prerequisite_tools}.",
        placeholders=frozenset({"prerequisite_tools"}),
    ),
    PromptKeySpec(
        key="guard.evidence.guidance",
        area=AREA,
        title="Evidence contract: guidance from the contract",
        seed=" Guidance from the contract: {guidance}",
        placeholders=frozenset({"guidance"}),
    ),
    PromptKeySpec(
        key="guard.evidence.incomplete_reminder",
        area=AREA,
        title="Incomplete evidence contract: do not answer from the compact result",
        seed=(
            "The last tool result has an incomplete evidence contract and is not safe as the sole basis for a "
            "definitive answer. Do not answer from the compact result alone. Incomplete evidence: "
            "{incomplete_evidence}.{artifact_hint} Otherwise run a narrower detailed Knowledge, Confluence, topology, "
            "database schema, database query, CodeGraph, or AWS intelligence lookup that preserves the missing "
            "evidence. If the evidence cannot be recovered, state exactly what is missing."
        ),
        placeholders=frozenset({"artifact_hint", "incomplete_evidence"}),
        risk=RISK_HIGH,
        description=(
            "{incomplete_evidence} lists 'tool: missing paths'; {artifact_hint} is the artifact hint key or empty."
        ),
    ),
    PromptKeySpec(
        key="guard.evidence.artifact_hint",
        area=AREA,
        title="Incomplete evidence contract: load the full artifact",
        seed=" If the full result is needed, call `load_tool_artifact` for {rendered_ids}.",
        placeholders=frozenset({"rendered_ids"}),
    ),
    PromptKeySpec(
        key="guard.evidence.hard_capped_label",
        area=AREA,
        title="Incomplete evidence contract: label without missing paths",
        seed="hard-capped compact evidence",
    ),
    PromptKeySpec(
        key="guard.coding.expected_paths_inspected",
        area=AREA,
        title="Governed coding: expected paths inspected, act now",
        seed=(
            "The approved expected paths have been inspected for this governed coding run: {expected_paths}. Do not "
            "inspect adjacent repository context unless you can name a concrete blocker that requires it. The next "
            "action must be one of: apply the approved file change with `edit_workspace_file`, "
            "`multi_edit_workspace_file`, or `apply_patch_workspace`; ask one precise clarification; or stop with a "
            "concrete blocker/no-op explanation."
        ),
        placeholders=frozenset({"expected_paths"}),
        risk=RISK_HIGH,
        description="{expected_paths} is the comma-separated list of inspected paths.",
    ),
    PromptKeySpec(
        key="guard.coding.evidence_budget",
        area=AREA,
        title="Governed coding: enough repository evidence",
        seed=(
            "You have enough repository evidence for this governed coding run. The next step must be one of: apply a "
            "file change with an edit/patch tool, ask a precise clarification, or finish with a concrete blocker/no-op "
            "explanation. Do not continue reading the same repository context."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="guard.coding.evidence_budget_stop",
        area=AREA,
        title="Stop: governed coding evidence budget exceeded",
        seed=(
            "this governed coding run used too many repository evidence tools without producing change, validation, "
            "commit, PR, or clarification evidence. Restart after tightening the approved plan, resolving blockers, or "
            "reducing ambiguity before spending more tokens."
        ),
        risk=RISK_HIGH,
        description=(
            "Persisted as the turn's stop answer after the fixed prefix 'Agent stopped because ' (kept in code)."
        ),
    ),
    PromptKeySpec(
        key="guard.stuck_loop.final_answer",
        area=AREA,
        title="Stuck retrieval loop: final answer now",
        seed=(
            "The retrieval loop is no longer adding useful new evidence. Stop calling tools now and write the best "
            "possible final answer from the evidence already gathered. Explicitly state any uncertainty or missing "
            "source coverage instead of searching again."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="guard.research.no_sources_stop",
        area=AREA,
        title="Stop: research step kept finding no usable sources",
        seed=(
            "the research-evidence step kept finding no usable sources for the requested document topic. Broaden the "
            "topic or provide concrete source hints before retrying."
        ),
        risk=RISK_HIGH,
        description=(
            "Persisted as the turn's stop answer after the fixed prefix 'Agent stopped because ' (kept in code)."
        ),
    ),
    PromptKeySpec(
        key="guard.artifact_loop.final_answer",
        area=AREA,
        title="Artifact loading loop: final answer now",
        seed=(
            "You already have enough evidence for the user's question. Do not call `load_tool_artifact` again. Write "
            "the final answer now using the gathered evidence."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="guard.progress.unsupported_claim",
        area=AREA,
        title="Premature completion claim without tool evidence",
        seed=(
            "The assistant made a {claim} claim without {missing}. {next_action} Do not finalize coding work from "
            "prose alone."
        ),
        placeholders=frozenset({"claim", "missing", "next_action"}),
        risk=RISK_HIGH,
        description=(
            "{claim} is the claim kind, {missing} the missing-evidence labels, {next_action} the next-action key."
        ),
    ),
    PromptKeySpec(
        key="guard.progress.completion_next_action",
        area=AREA,
        title="Premature completion: next action",
        seed="Continue with the next required state-machine action, or stop with a concrete blocker/no-op.",
    ),
    PromptKeySpec(
        key="guard.progress.missing_mutation",
        area=AREA,
        title="Missing evidence label: mutation",
        seed="mutation tool evidence",
    ),
    PromptKeySpec(
        key="guard.progress.missing_validation",
        area=AREA,
        title="Missing evidence label: validation",
        seed="validation tool evidence",
    ),
    PromptKeySpec(
        key="guard.progress.missing_delivery",
        area=AREA,
        title="Missing evidence label: delivery",
        seed="commit/PR delivery evidence",
    ),
    PromptKeySpec(
        key="guard.progress.missing_default",
        area=AREA,
        title="Missing evidence label: default",
        seed="state-machine completion evidence",
    ),
    PromptKeySpec(
        key="guard.progress.duplicate_read_only",
        area=AREA,
        title="Duplicate read-only call skipped (tool result note)",
        seed=(
            "This exact read-only tool call already succeeded. The runtime skipped duplicate execution and returned "
            "compact prior evidence."
        ),
    ),
    PromptKeySpec(
        key="guard.self_review.step_instructions",
        area=AREA,
        title="Synthetic Self Review step: instructions",
        seed=(
            "Before concluding a change flow, validate the outcome. Run `self_review_workspace_diff` and "
            "`build_pull_request_description`. Use `run_test_suite`, `lint_and_format_workspace`, or `run_sast_suite` "
            "when additional validation is needed."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="guard.self_review.step_success",
        area=AREA,
        title="Synthetic Self Review step: success criteria",
        seed="The result is reviewer-ready or an explicit blocker is documented.",
    ),
    PromptKeySpec(
        key="guard.self_review.incomplete_reminder",
        area=AREA,
        title="Self-review step not complete",
        seed=(
            "Step '{step_name}' is a required self-review stage and is not complete yet. Call "
            "`self_review_workspace_diff` first and only conclude after `build_pull_request_description` also ran."
        ),
        placeholders=frozenset({"step_name"}),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="guard.step.required_tool_reminder_unnamed",
        area=AREA,
        title="Step not complete: use an allowed tool",
        seed=(
            "This step is not complete yet. Use one of the allowed tools for the current step before marking it "
            "complete. Do not only describe the next action."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="guard.step.required_tool_reminder",
        area=AREA,
        title="Named step not complete: use an allowed tool",
        seed=(
            "Step '{step_name}' is not complete yet. Use one of the allowed tools for the current step before marking "
            "it complete. Do not only describe the next action."
        ),
        placeholders=frozenset({"step_name"}),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="guard.step.tool_required_stop",
        area=AREA,
        title="Stop: step must use a tool, the reply did not",
        seed=(
            "the step '{step_name}' must call one of its tools ({tool_names}) before it can finish, and its reply "
            "still called none after a reminder. This step called no tool; earlier steps of this run may already have "
            "completed. Rephrase the request so this step can use its tools, or, if this step does not need them, an "
            "administrator can set its tool use to optional on the agent page."
        ),
        placeholders=frozenset({"step_name", "tool_names"}),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="guard.step.stalled_stop",
        area=AREA,
        title="Stop: final step kept producing text without its tools",
        seed=(
            "the final step '{step_name}' kept producing text without using its required tools. The step definition or "
            "prompt needs correction before this run can complete reliably."
        ),
        placeholders=frozenset({"step_name"}),
        risk=RISK_HIGH,
        description=(
            "Persisted as the turn's stop answer after the fixed prefix 'Agent stopped because ' (kept in code)."
        ),
    ),
    PromptKeySpec(
        key="guard.step.stagnation_same_tool",
        area=AREA,
        title="Step stagnating: same tool repeatedly",
        seed=(
            "Step '{step_name}' is stagnating because it keeps calling `{tool_name}` without converging on a "
            "conclusion."
        ),
        placeholders=frozenset({"step_name", "tool_name"}),
    ),
    PromptKeySpec(
        key="guard.step.stagnation_off_contract",
        area=AREA,
        title="Step stagnating: tools outside the step contract",
        seed="Step '{step_name}' is stagnating because it repeatedly calls tools outside the current step contract.",
        placeholders=frozenset({"step_name"}),
    ),
    PromptKeySpec(
        key="guard.step.stagnation_jira",
        area=AREA,
        title="Step stagnating: Jira searches despite repository evidence",
        seed=(
            "Step '{step_name}' is stagnating because repository evidence is already available and the run keeps "
            "expanding Jira searches instead of moving on."
        ),
        placeholders=frozenset({"step_name"}),
    ),
    PromptKeySpec(
        key="guard.summary.missing_domains",
        area=AREA,
        title="Cross-system summary incomplete",
        seed=(
            "This cross-system summary is not complete yet. You still need to gather evidence for: {pretty_names}. Use "
            "the relevant tools for the missing domains before finalizing."
        ),
        placeholders=frozenset({"pretty_names"}),
        risk=RISK_HIGH,
        description="{pretty_names} lists the missing domains.",
    ),
    PromptKeySpec(
        key="guard.final_iteration",
        area=AREA,
        title="Final allowed iteration: answer now",
        seed=(
            "This is the final allowed iteration for this run. Do not call any more tools. Produce the final answer "
            "now from the evidence already gathered. Include concrete resource names, counts, denied or unknown calls, "
            "and residual risk. If the requested work cannot be completed from the gathered evidence, say exactly what "
            "is missing instead of continuing to investigate."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="guard.recovery.stuck_default",
        area=AREA,
        title="Recovery: default stuck message",
        seed="Step '{step_name}' is stuck.",
        placeholders=frozenset({"step_name"}),
    ),
    PromptKeySpec(
        key="guard.recovery.previous_step_summary",
        area=AREA,
        title="Recovery: previous step already summarized",
        seed=(
            "You already summarized the previous step. Do not restate the completed step again. Continue the CURRENT "
            "step now and call one of the allowed tools immediately."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="guard.recovery.duplicate_no_tool_stop",
        area=AREA,
        title="Stop: same no-tool response repeated",
        seed=(
            "step '{step_name}' kept producing the same no-tool response instead of making progress. Refine the prompt "
            "or adjust the step instructions before retrying."
        ),
        placeholders=frozenset({"step_name"}),
        risk=RISK_HIGH,
        description=(
            "Persisted as the turn's stop answer after the fixed prefix 'Agent stopped because ' (kept in code)."
        ),
    ),
    PromptKeySpec(
        key="guard.recovery.empty_search_stop",
        area=AREA,
        title="Stop: final step kept finding no search results",
        seed=(
            "the final step '{step_name}' kept finding no search results. Broaden the research topic or provide more "
            "specific source hints before retrying."
        ),
        placeholders=frozenset({"step_name"}),
        risk=RISK_HIGH,
        description=(
            "Persisted as the turn's stop answer after the fixed prefix 'Agent stopped because ' (kept in code)."
        ),
    ),
    PromptKeySpec(
        key="guard.recovery.move_to_next_step",
        area=AREA,
        title="Recovery: move to the next step",
        seed="{message} Move to the next step now.",
        placeholders=frozenset({"message"}),
        risk=RISK_HIGH,
        description="{message} is the stuck-loop event message.",
    ),
    PromptKeySpec(
        key="guard.recovery.iteration_ceiling_stop",
        area=AREA,
        title="Stop: final step kept calling tools",
        seed=(
            "the final step '{step_name}' kept calling tools without reaching a conclusion. Narrow the requested scope "
            "or adjust the step instructions before retrying."
        ),
        placeholders=frozenset({"step_name"}),
        risk=RISK_HIGH,
        description=(
            "Persisted as the turn's stop answer after the fixed prefix 'Agent stopped because ' (kept in code)."
        ),
    ),
    PromptKeySpec(
        key="guard.recovery.looping_stop",
        area=AREA,
        title="Stop: final step kept looping",
        seed=(
            "the final step '{step_name}' kept looping without reaching a conclusion. Narrow the requested scope or "
            "adjust the step instructions before retrying."
        ),
        placeholders=frozenset({"step_name"}),
        risk=RISK_HIGH,
        description=(
            "Persisted as the turn's stop answer after the fixed prefix 'Agent stopped because ' (kept in code)."
        ),
    ),
    PromptKeySpec(
        key="guard.recovery.iteration_ceiling_wrapup",
        area=AREA,
        title="Recovery: iteration ceiling, conclude now",
        seed=(
            "The final step '{step_name}' has already used enough tool iterations. Do not continue searching. Based on "
            "the evidence already gathered, either perform the required change now using the allowed write tools or "
            "conclude explicitly that no update is required."
        ),
        placeholders=frozenset({"step_name"}),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="guard.recovery.force_wrapup",
        area=AREA,
        title="Recovery: stop researching and conclude",
        seed=(
            "{message} Stop researching and conclude the current step now with a concrete answer or a clear no-op "
            "justification."
        ),
        placeholders=frozenset({"message"}),
        risk=RISK_HIGH,
        description="{message} is the stuck-loop event message.",
    ),
)
