"""The synthetic agent definition (steps, tools, budgets) a coding workflow contract runs under."""

from __future__ import annotations

from typing import Any

from ..prompt_catalog import render_prompt

# Delivery hand-off tools for governed coding runs, resolved per provider —
# the change units' source-control provider picks the push/PR tools, the work
# item's ticket system picks the ticket-update tool. Unknown providers resolve
# to NO delivery step (deny-by-default), never to a guessed toolset.
SOURCE_CONTROL_DELIVERY_TOOLS: dict[str, tuple[str, ...]] = {
    "bitbucket": ("commit_and_push_repository_branch", "create_bitbucket_pull_request"),
}
TICKET_DELIVERY_TOOLS: dict[str, tuple[str, ...]] = {
    "jira": ("add_jira_comment",),
}
# Union across providers: the registry phase toolset and the step allowedTools
# intersect, so the phase list must cover every resolvable delivery tool
# (a tool missing from either list is unavailable to the model).
ALL_CODING_DELIVERY_TOOLS: tuple[str, ...] = tuple(
    dict.fromkeys(
        tool
        for tools in (*SOURCE_CONTROL_DELIVERY_TOOLS.values(), *TICKET_DELIVERY_TOOLS.values())
        for tool in tools
    )
)


def resolve_coding_delivery_tools(delivery: dict[str, Any] | None) -> tuple[str, ...]:
    """Resolve the delivery toolset from the run's provider context.

    Both providers must be known and mapped; otherwise the run gets no
    delivery step and the reason is visible in the (empty) resolution.
    """
    context = delivery if isinstance(delivery, dict) else {}
    source_control = str(context.get("source_control_provider") or "").strip().lower()
    ticket = str(context.get("ticket_provider") or "").strip().lower()
    source_tools = SOURCE_CONTROL_DELIVERY_TOOLS.get(source_control)
    ticket_tools = TICKET_DELIVERY_TOOLS.get(ticket)
    if not source_tools or not ticket_tools:
        return ()
    return (*source_tools, *ticket_tools)

# Step iteration budgets. 32 came from live evidence (a 44-block cleanup died
# at 20 while converging); 8 bounds the mechanical delivery hand-off.
CODING_STEP_ITERATIONS = 20
CODING_CONTRACT_STEP_ITERATIONS = 32
CODING_DELIVERY_STEP_ITERATIONS = 8


def build_workflow_agent_definition(workflow_contract: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(workflow_contract, dict) or not workflow_contract:
        return None
    if str(workflow_contract.get("workflow_id") or "").strip() != "coding_change_tdd":
        return None
    topic = str(workflow_contract.get("topic") or "the requested topic").strip()
    # Approved verification contract (LLM-proposed at plan time, human-
    # approved, resolved per run): when present, IT is the completion gate
    # instead of the one-size-fits-all test-suite criterion — a Terraform
    # cleanup verifies via its approved commands, a Java change via mvn.
    verification_contract = workflow_contract.get("verification_contract")
    verification_commands = [
        str(entry.get("command") or "").strip()
        for entry in ((verification_contract or {}).get("commands") or [])
        if isinstance(entry, dict) and str(entry.get("command") or "").strip()
    ]
    allowed_tools = [
        "bootstrap_workspace_repository",
        "analyze_workspace_repository",
        "code_search",
        "code_symbol_definition",
        "code_references",
        "code_file_outline",
        "code_impact_analysis",
        "list_workspace_directory",
        "read_workspace_file",
        "write_workspace_file",
        "edit_workspace_file",
        "multi_edit_workspace_file",
        "apply_patch_workspace",
        "run_test_suite",
    ]
    if verification_commands:
        allowed_tools.append("run_validation_commands")
        command_lines = "; ".join(verification_commands[:8])
        verify_sentence = render_prompt("coding.change.verify_sentence.contract", command_lines=command_lines)
        instructions = render_prompt("coding.change.instructions.contract")
        success_criteria = render_prompt("coding.change.success.contract")
    else:
        verify_sentence = render_prompt("coding.change.verify_sentence.tdd")
        instructions = render_prompt("coding.change.instructions.tdd")
        success_criteria = render_prompt("coding.change.success.tdd")
    if verification_commands:
        # The phase machine must carry the contract too — otherwise its
        # per-iteration reminders keep demanding run_test_suite and fight
        # the step instructions.
        tdd_cycle_phases: list[Any] = [
            {
                "name": "verify_contract",
                "title": "Implement And Verify Contract",
                "instructions": render_prompt("coding.tdd.phase.verify_contract"),
                "completion_rule": "validation_green",
                "required_tools": ["run_validation_commands"],
            }
        ]
    else:
        tdd_cycle_phases = ["write_tests", "make_green"]
    steps: list[dict[str, Any]] = [
        {
            "name": "Implement And Verify Change",
            "stepType": "tdd_cycle",
            "instructions": instructions,
            "successCriteria": success_criteria,
            "allowedTools": allowed_tools,
            "stepConfig": {
                "tool_use": "required",
                # A verification contract implies multi-file work: allow
                # enough iterations for it.
                "max_iterations": (
                    CODING_CONTRACT_STEP_ITERATIONS if verification_commands else CODING_STEP_ITERATIONS
                ),
                "tdd_cycle_phases": tdd_cycle_phases,
            },
            "isEnabled": True,
        },
    ]
    delivery_tools = resolve_coding_delivery_tools(workflow_contract.get("delivery"))
    if verification_commands and delivery_tools:
        # Governed executions end with an explicit delivery hand-off; the
        # operating model is implement -> verify -> deliver. Plain chat
        # coding (no approved contract) never auto-delivers, and unknown
        # providers resolve to no delivery step instead of a guessed one.
        steps.append(
            {
                "name": "Deliver Change",
                "stepType": "change",
                "instructions": render_prompt("coding.delivery.instructions"),
                "successCriteria": render_prompt("coding.delivery.success"),
                "allowedTools": ["get_git_diff", *delivery_tools],
                "stepConfig": {"tool_use": "required", "max_iterations": CODING_DELIVERY_STEP_ITERATIONS},
                "isEnabled": True,
            }
        )
    return {
        "name": "Code Change TDD",
        "agentType": "change",
        "prompt": render_prompt("coding.change.agent_prompt", topic=topic, verify_sentence=verify_sentence),
        "steps": steps,
    }
