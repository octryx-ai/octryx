"""Seeds of the agent loop's response guards: reminders, nudges and stop texts.

Injected by ``agent/loops/response/*`` as system messages or persisted as the turn's
stop answer. Stop texts are stored without their protocol prefix ``Agent stopped because ``
(``agent/core/guards/stop_text.py``), which session state detection matches.
"""

from __future__ import annotations

from ..contract import RISK_HIGH, PromptKeySpec

AREA = "loop"

SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="loop.pseudo_tool_call.retry_reminder",
        area=AREA,
        title="Pseudo tool call: retry reminder",
        seed=(
            "Your last reply wrote tool calls as text that could not be executed. Call an offered tool through the "
            "tool-call channel now, or answer only from evidence already collected."
        ),
        risk=RISK_HIGH,
        description="System message after a reply that wrote tool calls as text; the reply is suppressed.",
    ),
    PromptKeySpec(
        key="loop.pseudo_tool_call.refusal",
        area=AREA,
        title="Pseudo tool call: closed refusal",
        seed=(
            "The model wrote tool calls as text{written} instead of calling tools. Text is never executed, so nothing "
            "was run and there is no evidence-backed answer. {cause} Send the request again; if this repeats, choose a "
            "runtime with reliable tool calling or check the workflow's tool configuration."
        ),
        placeholders=frozenset({"cause", "written"}),
        risk=RISK_HIGH,
        description=(
            "Final answer when the model repeats pseudo tool calls. {written} is ' (name, ...)' or empty; {cause} is "
            "one of the two cause keys."
        ),
    ),
    PromptKeySpec(
        key="loop.pseudo_tool_call.cause_tools_offered",
        area=AREA,
        title="Pseudo tool call: cause (tools offered)",
        seed="It kept doing so after a reminder.",
    ),
    PromptKeySpec(
        key="loop.pseudo_tool_call.cause_no_tools",
        area=AREA,
        title="Pseudo tool call: cause (no tools offered)",
        seed="No tools were offered to the model in this turn, and it kept doing so after a reminder.",
    ),
    PromptKeySpec(
        key="loop.transition.transition_reminder",
        area=AREA,
        title="Transition sentence nudge",
        seed=(
            "Do not stop at a transition sentence. Continue immediately: either call the next relevant tool now or "
            "answer directly with concrete evidence if you already have enough information."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="loop.transition.transition_stop",
        area=AREA,
        title="Stop: repeated transition text",
        seed=(
            "the run kept producing transition text without taking the next tool action. Restart with clearer scope, a "
            "narrower tool set, or an explicit blocker decision."
        ),
        risk=RISK_HIGH,
        description=(
            "Persisted as the turn's stop answer after the fixed prefix 'Agent stopped because ' (kept in code)."
        ),
    ),
    PromptKeySpec(
        key="loop.transition.placeholder_reminder",
        area=AREA,
        title="Placeholder or empty acknowledgement nudge",
        seed=(
            "Do not end with a placeholder or empty acknowledgement. Continue immediately: call the next relevant tool "
            "now, or answer with a concrete explanation backed by the evidence already collected."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="loop.transition.placeholder_stop",
        area=AREA,
        title="Stop: repeated placeholder or textual tool requests",
        seed=(
            "the selected runtime kept producing placeholder or textual tool-request responses without making "
            "progress. Choose a runtime with reliable tool calling or provide a more specific project context."
        ),
        risk=RISK_HIGH,
        description=(
            "Persisted as the turn's stop answer after the fixed prefix 'Agent stopped because ' (kept in code)."
        ),
    ),
    PromptKeySpec(
        key="loop.followup.no_tool_stop",
        area=AREA,
        title="Stop answer: repeated no-tool follow-up loop",
        seed=(
            "I could not complete the required follow-up action with the selected runtime. The agent kept producing "
            "text without using its required tools, so I stopped the repeated no-tool loop and kept the collected "
            "evidence available for continuation. Continue the session with a runtime/tool policy that can perform the "
            "required action, or ask for a bounded summary from the evidence already gathered."
        ),
        risk=RISK_HIGH,
        description="Persisted answer when a required follow-up action never ran and the model left no usable draft.",
    ),
    PromptKeySpec(
        key="loop.followup.artifact_required_at",
        area=AREA,
        title="Workflow contract: artifact still required (with path)",
        seed="The workflow contract still requires a finished artifact at `{artifact_path}`.",
        placeholders=frozenset({"artifact_path"}),
        risk=RISK_HIGH,
        description="First sentence of the unsatisfied-contract reminder; followed by the workflow instruction.",
    ),
    PromptKeySpec(
        key="loop.followup.artifact_required",
        area=AREA,
        title="Workflow contract: artifact still required",
        seed="The workflow contract still requires a finished artifact.",
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="loop.followup.evidence_required",
        area=AREA,
        title="Workflow contract: grounding evidence still required",
        seed="The workflow contract still requires grounding evidence before you answer.",
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="loop.followup.instruction.knowledge_request",
        area=AREA,
        title="Unsatisfied contract: Knowledge request (citations)",
        seed=(
            "Do not answer yet. Retrieve the required evidence first with knowledge_search, then answer grounded "
            "strictly in what you found, citing each source as a link to its source_url. Do not build or promise a "
            "deliverable (deck, document) that was not requested."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="loop.followup.instruction.other",
        area=AREA,
        title="Unsatisfied contract: other evidence workflows",
        seed=(
            "Do not answer yet. Retrieve the required evidence first with the available knowledge tools (e.g. "
            "knowledge_search / knowledge_read), then answer grounded strictly in what you found. Do not build or "
            "promise a deliverable (deck, document) that was not requested."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="loop.contract_satisfied",
        area=AREA,
        title="Workflow contract satisfied: answer now",
        seed=(
            "The workflow contract is already satisfied. Do not call any more tools. Write the final user-facing "
            "answer now from the evidence already gathered."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="loop.meta_final_reply",
        area=AREA,
        title="Meta 'ready to finalize' reply rejected",
        seed=(
            "Do not answer with a meta statement about being ready to finalize. Write the final user-facing answer now "
            "using the workflow evidence already gathered."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="loop.tdd.validation_contract_unproven",
        area=AREA,
        title="Step completion rejected: verification contract unproven",
        seed=(
            "Step completion rejected: the verification contract has not been proven in this run. Existing branch "
            "state does not count. Call run_validation_commands now; if commands fail, implement the missing changes "
            "until every command exits 0, then finish the step."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="loop.mermaid_instead_of_diagram",
        area=AREA,
        title="Mermaid fence instead of a diagram artifact",
        seed=(
            "Your reply contains a mermaid code fence, but the user asked for a diagram: on this platform diagrams are "
            "delivered as draw.io artifacts, never as mermaid text. Pick the matching workflow from the workflow "
            "catalog with select_workflow (conceptual/developer diagrams: 'diagram') and let the "
            "deterministic builder render it via create_diagram. Answer again using the tools."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="loop.snapshot_evidence_reminder",
        area=AREA,
        title="Evidence snapshot collected: create the diagram next",
        seed=(
            "Evidence snapshot collected: {snapshot_tool} succeeded. The evidence for the diagram now exists — call "
            "create_diagram next and render deterministically from the snapshot evidence only (for topology snapshots: "
            "exactly the diagram_brief selected_nodes/selected_edges). Do not repeat the snapshot and do not invent "
            "nodes or relationships."
        ),
        placeholders=frozenset({"snapshot_tool"}),
        risk=RISK_HIGH,
        description="{snapshot_tool} is the snapshot tool that just succeeded.",
    ),
    PromptKeySpec(
        key="loop.artifact_ready.knowledge",
        area=AREA,
        title="Knowledge evidence complete: final answer now",
        seed=(
            "The Knowledge evidence phase is complete. Do not call any more tools. Write the final user-facing answer "
            "now using only the retrieved Knowledge evidence. Cite Knowledge keys, titles, or sources when available. "
            "Separate direct evidence from inference, and do not claim there were no assumptions if you include any "
            "inference."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="loop.artifact_ready.at_path",
        area=AREA,
        title="Workflow artifact built: final answer now (with path)",
        seed=(
            "The required workflow artifact is already built and validated at `{artifact_path}`. Do not call any more "
            "tools. Write the final user-facing answer now and mention the artifact path."
        ),
        placeholders=frozenset({"artifact_path"}),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="loop.artifact_ready.no_path",
        area=AREA,
        title="Workflow artifact built: final answer now",
        seed=(
            "The required workflow artifact is already built and validated. Do not call any more tools. Write the "
            "final user-facing answer now and mention the artifact path."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="loop.coding.inspection_not_enough",
        area=AREA,
        title="Coding nudge: inspection is not enough",
        seed=(
            "This is a coding task. Repository inspection alone is not enough. Do not restate the request or describe "
            "intent only. Execute the next relevant coding or verification tool now."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="loop.coding.no_evidence_stop",
        area=AREA,
        title="Stop: coding run without tool evidence",
        seed=(
            "this coding run did not produce workspace inspection or coding-tool evidence. Restart with a clearer "
            "approved plan, a narrower repository scope, or an explicit blocker decision."
        ),
        risk=RISK_HIGH,
        description=(
            "Persisted as the turn's stop answer after the fixed prefix 'Agent stopped because ' (kept in code)."
        ),
    ),
    PromptKeySpec(
        key="loop.coding.analysis_only",
        area=AREA,
        title="Governed coding still in analysis-only mode",
        seed=(
            "This governed coding run is still in analysis-only mode. Use `edit_workspace_file`, "
            "`multi_edit_workspace_file`, or `apply_patch_workspace` for the approved change; then run the required "
            "validation and prepare commit/PR evidence. If the approved change is unsafe or impossible, stop with an "
            "explicit blocker instead of continuing analysis."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="loop.coding.analysis_only_stop",
        area=AREA,
        title="Stop: governed plan analyzed, nothing delivered",
        seed=(
            "the selected runtime analyzed the governed coding plan but did not produce change, validation, commit, "
            "PR, or explicit blocker evidence. Restart after tightening the approved plan, narrowing the scope, or "
            "capturing a human blocker decision."
        ),
        risk=RISK_HIGH,
        description=(
            "Persisted as the turn's stop answer after the fixed prefix 'Agent stopped because ' (kept in code)."
        ),
    ),
    PromptKeySpec(
        key="loop.coding.narration",
        area=AREA,
        title="Coding nudge: do not narrate the next step",
        seed=(
            "This is a coding task. Do not narrate the next step. Execute the next relevant coding or verification "
            "tool now."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="loop.coding.narration_stop",
        area=AREA,
        title="Stop: kept describing the next coding step",
        seed=(
            "the run kept describing the next coding step instead of executing it. Restart with a clearer approved "
            "plan, a narrower tool scope, or an explicit blocker decision."
        ),
        risk=RISK_HIGH,
        description=(
            "Persisted as the turn's stop answer after the fixed prefix 'Agent stopped because ' (kept in code)."
        ),
    ),
)
