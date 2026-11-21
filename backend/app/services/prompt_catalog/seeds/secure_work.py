"""Seeds of the governed secure-work prompts: the governed coding agent's execution prompt, the
verification and workspace lines, the Work Plan author, the CI/CD, review and external-activity
agent instructions, the rejected-approval resume note, the delivery gate and the Claude Code
gateway's deny and verification messages.

The only code copy of these texts. Fact lines (state machine, runtime contract, workspace records,
command lines) and the Work Plan JSON schema the parser validates stay in code.
"""

from __future__ import annotations

from ..contract import RISK_HIGH, PromptKeySpec

AREA = "secure_work"

SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="secure_work.coding.execution_prompt",
        area=AREA,
        title="Governed coding agent: execution prompt",
        seed=(
            "You are Octryx's governed coding agent.\n"
            "Execute this approved Work Plan through platform tools only; do not rely on hidden manual work.\n"
            "\n"
            "Hard requirements:\n"
            "- Use repository/workspace tools to prepare the repository and working branch.\n"
            "- Change only files inside the approved expected paths.\n"
            "- Do not deploy, merge, or close the Jira issue.\n"
            "- If the source task, approved scope, repository state, or policy evidence conflicts, stop and report "
            "blockers.\n"
            "- Record validation evidence, diff evidence, and next human review actions in the final answer.\n"
            "\n"
            "Runtime state machine:\n"
            "{state_machine_block}{execution_contract_block}\n"
            "Delivery tools you may need:\n"
            "- apply_patch_workspace / edit_workspace_file / multi_edit_workspace_file for file changes.\n"
            "- run_cli_command for local validation only after changes are made.\n"
            "- commit_and_push_repository_branch and create_bitbucket_pull_request for review handoff.\n"
            "- ask_clarification only when the approved plan or source evidence is insufficient or conflicting.\n"
            "\n"
            "Work Item: {source_key}\n"
            "Title: {title}\n"
            "Jira status: {source_status}\n"
            "Source URL: {source_url}\n"
            "Description:\n"
            "{description}\n"
            "\n"
            "Approved Work Plan v{plan_version}: {plan_title}\n"
            "Understood request:\n"
            "{understood_request}\n"
            "Rollback plan:\n"
            "{rollback_plan}\n"
            "\n"
            "Approved repositories and paths:\n"
            "{unit_block}\n"
            "{verification_block}\n"
            "Pipeline preflight:\n"
            "- run_id: {run_id}\n"
            "- status: {run_status}\n"
            "\n"
            "Prepared coding workspaces:\n"
            "{workspace_block}\n"
            "Restart context:\n"
            "{restart_line}\n"
            "\n"
            "Operator request:\n"
            "{operator_request}"
        ),
        placeholders=frozenset(
            {
                "description",
                "execution_contract_block",
                "operator_request",
                "plan_title",
                "plan_version",
                "restart_line",
                "rollback_plan",
                "run_id",
                "run_status",
                "source_key",
                "source_status",
                "source_url",
                "state_machine_block",
                "title",
                "understood_request",
                "unit_block",
                "verification_block",
                "workspace_block",
            }
        ),
        risk=RISK_HIGH,
        description=(
            "First message of a governed coding execution. Each *_block placeholder is a block of lines, each ending "
            "with a newline (empty when there are none); the other placeholders are Work Item and Work Plan facts."
        ),
    ),
    PromptKeySpec(
        key="secure_work.coding.restart_from_scratch",
        area=AREA,
        title="Governed coding agent: restart from scratch",
        seed=(
            "- Operator requested restart from scratch. Treat previous implementation attempts as audit evidence only; "
            "do not continue a flawed direction unless it is independently justified by the approved plan."
        ),
        risk=RISK_HIGH,
        description="Fills {restart_line} on an operator restart.",
    ),
    PromptKeySpec(
        key="secure_work.coding.normal_start",
        area=AREA,
        title="Governed coding agent: normal start",
        seed="- Normal governed start.",
        description="Fills {restart_line} otherwise.",
    ),
    PromptKeySpec(
        key="secure_work.coding.default_rollback_plan",
        area=AREA,
        title="Governed coding agent: default rollback plan",
        seed="Close or revert the resulting PR/commit.",
        description="Used when the Work Plan has no rollback plan.",
    ),
    PromptKeySpec(
        key="secure_work.coding.default_operator_request",
        area=AREA,
        title="Governed coding agent: default operator request",
        seed="Implement the approved Work Plan and prepare review evidence.",
        description="Used when the operator left no note.",
    ),
    PromptKeySpec(
        key="secure_work.coding.no_change_units",
        area=AREA,
        title="Governed coding agent: no Change Units",
        seed="- No Change Units are selected. Stop and report this blocker.",
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="secure_work.workspace.none_prepared",
        area=AREA,
        title="Governed coding agent: no workspace prepared",
        seed="- No workspace record was prepared. Stop and report this blocker.",
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="secure_work.verification.none_resolved",
        area=AREA,
        title="Verification contract: none resolved",
        seed=(
            "Verification contract: none resolved — verify via run_test_suite (auto-detected framework) and report its "
            "result."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="secure_work.verification.header",
        area=AREA,
        title="Verification contract: header",
        seed=(
            "Verification contract (the change is DONE when every command below exits 0 — run them with "
            "run_validation_commands):"
        ),
        risk=RISK_HIGH,
        description="Followed by one line per command.",
    ),
    PromptKeySpec(
        key="secure_work.verification.criteria_header",
        area=AREA,
        title="Verification contract: acceptance criteria header",
        seed="Acceptance criteria these commands prove (the change must satisfy ALL of them):",
    ),
    PromptKeySpec(
        key="secure_work.verification.closing",
        area=AREA,
        title="Verification contract: closing line",
        seed=(
            "Where a test framework exists you should additionally write or extend focused tests for the change; the "
            "contract above is the completion gate."
        ),
    ),
    PromptKeySpec(
        key="secure_work.work_plan.system",
        area=AREA,
        title="Work Plan author: system prompt",
        seed=(
            "You author enterprise Work Plans from Jira evidence. Use only the supplied evidence. Do not invent "
            "repositories, files, people, statuses, releases, or validation commands. If evidence is missing, add an "
            "open question. Not every Work Item is a coding change; classify the work type honestly. Every requirement "
            "clause of the work item MUST appear as an acceptance criterion mapped to validation commands (from "
            "validation_plan, exact text) that prove it. A clause you cannot map to an enforceable command must become "
            "an open question instead of a criterion without commands. Return only valid JSON matching the requested "
            "schema."
        ),
        risk=RISK_HIGH,
        description="System message of the LLM Work Plan author; the user message with the JSON schema stays code.",
    ),
    PromptKeySpec(
        key="secure_work.cicd.findings_instruction",
        area=AREA,
        title="CI/CD findings: agent instruction",
        seed="Use current CI/CD findings as remediation evidence; ignore stale_ignored findings for current state.",
    ),
    PromptKeySpec(
        key="secure_work.cicd.failure_instruction",
        area=AREA,
        title="CI/CD failure context: agent instruction",
        seed=(
            "Use CI/CD failure context as remediation evidence. Preserve the linked job, build, stage, failure "
            "taxonomy, and bounded log excerpt when planning fixes."
        ),
    ),
    PromptKeySpec(
        key="secure_work.review.feedback_instruction",
        area=AREA,
        title="Review feedback: agent instruction",
        seed=(
            "Respect human edits and review comments. Do not silently revert reviewer changes; explain any conflict "
            "and request approval before overriding human-authored content."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="secure_work.external_activity.instruction",
        area=AREA,
        title="External activity: agent instruction",
        seed=(
            "Before continuing implementation, inspect external activity. If current_flags.requires_replan is true, "
            "re-read the linked source evidence, update the plan, and explain how the external event changed the work. "
            "Do not continue from stale assumptions."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="secure_work.approval.rejected_resume",
        area=AREA,
        title="Rejected approval: resume note",
        seed=(
            "{original_prompt}\n"
            "\n"
            "Resume note: the previously requested approval was rejected. Rejected action: {action}.\n"
            "Rejection reason: {rejection_reason}\n"
            "Do not attempt the rejected action or equivalent risky changes. Acknowledge the rejection briefly and "
            "provide the safest next step or read-only alternative."
        ),
        placeholders=frozenset({"action", "original_prompt", "rejection_reason"}),
        risk=RISK_HIGH,
        description="Resume prompt after a rejected approval; {original_prompt} is the paused turn's prompt.",
    ),
    PromptKeySpec(
        key="secure_work.approval.default_rejection_reason",
        area=AREA,
        title="Rejected approval: default reason",
        seed="The approval request was rejected.",
        description="Fills {rejection_reason} when the approver gave none.",
    ),
    PromptKeySpec(
        key="secure_work.approval.default_action",
        area=AREA,
        title="Rejected approval: default action label",
        seed="approval-required action",
        description="Fills {action} when the approval names no action.",
    ),
    PromptKeySpec(
        key="secure_work.delivery.validation_missing",
        area=AREA,
        title="Delivery blocked: validation missing",
        seed=(
            "This is a governed coding run: no delivery is allowed before the approved verification contract is proven "
            "in THIS session. Call run_validation_commands and make every command exit 0 (all_green). If commands "
            "fail, implement the missing changes first - previous runs or existing branch state do not count as proof."
        ),
        risk=RISK_HIGH,
        description="Refusal detail of a delivery tool before the verification contract is proven.",
    ),
    PromptKeySpec(
        key="secure_work.content.masked_note",
        area=AREA,
        title="Content policy: values were masked",
        seed=(
            "Some values in this conversation were masked by the Octryx policy {policies}. Placeholders "
            "such as [EMAIL #1] are not real values: do not search for them, change "
            "them or ask for the originals. Refer to them by their placeholder."
        ),
        placeholders=frozenset({"policies"}),
        risk=RISK_HIGH,
        description="System note added to a model request whose content a policy obligation masked.",
    ),
    PromptKeySpec(
        key="secure_work.gateway.unparseable_command",
        area=AREA,
        title="Gateway: command not parseable",
        seed=(
            "Octryx could not parse this shell command safely. Simplify it (balanced quotes, no oversized "
            "inline content) and retry."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="secure_work.gateway.deny.command_prefix_denied",
        area=AREA,
        title="Gateway deny: command_prefix_denied",
        seed="Octryx policy denies this command (rule {rule_id}). Do not retry it.",
        placeholders=frozenset({"rule_id"}),
        risk=RISK_HIGH,
        description="Message of a Claude Code tool call the Workspace policy denies.",
    ),
    PromptKeySpec(
        key="secure_work.gateway.deny.command_requires_argument",
        area=AREA,
        title="Gateway deny: command_requires_argument",
        seed="Octryx policy requires {argument} on this command (rule {rule_id}). Add it explicitly and retry.",
        placeholders=frozenset({"argument", "rule_id"}),
        risk=RISK_HIGH,
        description="Message of a Claude Code tool call the Workspace policy denies.",
    ),
    PromptKeySpec(
        key="secure_work.gateway.deny.command_argument_denied",
        area=AREA,
        title="Gateway deny: command_argument_denied",
        seed="Octryx policy denies {argument} on this command (rule {rule_id}). Do not retry it.",
        placeholders=frozenset({"argument", "rule_id"}),
        risk=RISK_HIGH,
        description="Message of a Claude Code tool call the Workspace policy denies.",
    ),
    PromptKeySpec(
        key="secure_work.gateway.deny.path_denied",
        area=AREA,
        title="Gateway deny: path_denied",
        seed="Octryx policy denies this path for {tool} (rule {rule_id}). Do not access it.",
        placeholders=frozenset({"rule_id", "tool"}),
        risk=RISK_HIGH,
        description="Message of a Claude Code tool call the Workspace policy denies.",
    ),
    PromptKeySpec(
        key="secure_work.gateway.deny.cedar_policy",
        area=AREA,
        title="Gateway deny: Cedar policy",
        seed=(
            "Octryx policy denies this tool call (policy {policy_ids}; decision {decision_id}, see Settings → "
            "Governance → Policy decisions). Do not retry it."
        ),
        placeholders=frozenset({"policy_ids", "decision_id"}),
        risk=RISK_HIGH,
        description="Message of a Claude Code tool call a published Cedar policy denies in enforce mode.",
    ),
    PromptKeySpec(
        key="secure_work.gateway.gate.no_test_after_last_change",
        area=AREA,
        title="Gateway verification gate: no_test_after_last_change",
        seed=(
            "Octryx gate: you changed files after the last green focused test. Run the focused tests for your "
            "change (e.g. pytest <paths>) and only finish when they pass."
        ),
        risk=RISK_HIGH,
        description="Detail of the gateway verification gate for this reason.",
    ),
    PromptKeySpec(
        key="secure_work.gateway.gate.last_test_failed",
        area=AREA,
        title="Gateway verification gate: last_test_failed",
        seed=(
            "Octryx gate: the last focused test after your change failed. Fix the failure, rerun the focused "
            "tests and only finish when they pass."
        ),
        risk=RISK_HIGH,
        description="Detail of the gateway verification gate for this reason.",
    ),
    PromptKeySpec(
        key="secure_work.gateway.gate.last_test_unconfirmed",
        area=AREA,
        title="Gateway verification gate: last_test_unconfirmed",
        seed=(
            "Octryx gate: the result of your last focused test run was not seen. Rerun the focused tests for "
            "your change and only finish when they pass."
        ),
        risk=RISK_HIGH,
        description="Detail of the gateway verification gate for this reason.",
    ),
    PromptKeySpec(
        key="secure_work.gateway.gate.last_test_not_run",
        area=AREA,
        title="Gateway verification gate: last_test_not_run",
        seed=(
            "Octryx gate: the focused test did not run (it was refused before execution). Run it so it "
            "executes, and only finish when it passes."
        ),
        risk=RISK_HIGH,
        description="Detail of the gateway verification gate for this reason.",
    ),
    PromptKeySpec(
        key="secure_work.gateway.gate.verification_not_configured",
        area=AREA,
        title="Gateway verification gate: verification_not_configured",
        seed=(
            "Octryx gate: this Workspace declares no test commands, so completion cannot be verified. Ask a "
            "Workspace admin to configure agent_gateway_policy.verification."
        ),
        risk=RISK_HIGH,
        description="Detail of the gateway verification gate for this reason.",
    ),
)
