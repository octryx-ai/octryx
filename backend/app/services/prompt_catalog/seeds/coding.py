"""Seeds of the coding prompts: TDD phases and reminders and the coding-change workflow agent.

The only code copy of these texts; the catalog serves the published version.
"""

from __future__ import annotations

from ..contract import RISK_HIGH, PromptKeySpec

AREA = "coding"

SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="coding.tdd.phase.write_tests",
        area=AREA,
        title="TDD phase instructions: Write Tests",
        seed=(
            "Add or update focused tests for the requested change first. Before writing implementation code, inspect "
            "the affected area with native graph tools such as `code_graph_status`, `code_explore`, `code_context`, "
            "`code_trace`, or `code_impact` before broad file scanning; use `code_search`, `code_symbol_definition`, "
            "`code_references`, or `code_impact_analysis` when useful. If a graph response marks a file stale, read "
            "that file directly before relying on snippets. Then call `run_test_suite` to capture the failing or "
            "baseline state before implementation."
        ),
        description=(
            "Instructions of the write_tests phase of a tdd_cycle step, unless the step config supplies its own."
        ),
    ),
    PromptKeySpec(
        key="coding.tdd.phase.make_green",
        area=AREA,
        title="TDD phase instructions: Make Green",
        seed=(
            "Implement or adjust the code until the relevant test suite is green. Use repository intelligence and "
            "native graph context tools to validate symbol locations and impact before broad edits. Call "
            "`run_test_suite` again after changes and stay in this phase until `all_green` is true."
        ),
        description=(
            "Instructions of the make_green phase of a tdd_cycle step, unless the step config supplies its own."
        ),
    ),
    PromptKeySpec(
        key="coding.tdd.phase.refactor",
        area=AREA,
        title="TDD phase instructions: Refactor and Lint",
        seed=(
            "Clean up the implementation and run `lint_and_format_workspace`. This phase is complete only when lint "
            "and format checks are clean."
        ),
        description="Instructions of the refactor phase of a tdd_cycle step, unless the step config supplies its own.",
    ),
    PromptKeySpec(
        key="coding.tdd.phase.self_review",
        area=AREA,
        title="TDD phase instructions: Self Review",
        seed=(
            "Review the current diff with `self_review_workspace_diff`, address any findings, then call "
            "`build_pull_request_description`. Only finish when the review is PR-ready."
        ),
        description=(
            "Instructions of the self_review phase of a tdd_cycle step, unless the step config supplies its own."
        ),
    ),
    PromptKeySpec(
        key="coding.tdd.phase.security_review",
        area=AREA,
        title="TDD phase instructions: Security Review",
        seed=(
            "Run `run_sast_suite` and keep this phase open until security scanning is clean or the remaining risk is "
            "explicitly documented for the final handoff."
        ),
        description="Instructions of the optional security_review phase template.",
    ),
    PromptKeySpec(
        key="coding.tdd.required_tools_suffix",
        area=AREA,
        title="TDD reminder: required tools suffix",
        seed=" Required tools: {required_tools}.",
        placeholders=frozenset({"required_tools"}),
        description=(
            "Appended to the incomplete reminder when the phase names required tools ({required_tools}: comma "
            "list)."
        ),
    ),
    PromptKeySpec(
        key="coding.tdd.incomplete_reminder",
        area=AREA,
        title="TDD reminder: step not complete",
        seed=(
            "Step '{step_name}' is a structured TDD cycle and is not complete yet. Current phase: {phase_title} "
            "({phase_number}/{phase_total}). {phase_instructions}{tools_suffix}"
        ),
        placeholders=frozenset(
            {
                "phase_instructions",
                "phase_number",
                "phase_title",
                "phase_total",
                "step_name",
                "tools_suffix",
            }
        ),
        risk=RISK_HIGH,
        description=(
            "Injected when a tdd_cycle step tries to finish early. {tools_suffix} is the rendered suffix or empty."
        ),
    ),
    PromptKeySpec(
        key="coding.tdd.complete",
        area=AREA,
        title="TDD progress: all phases complete",
        seed=(
            "All TDD cycle phases are complete. Do not keep calling verification tools. Provide the final completion "
            "update now."
        ),
        description="Injected once every TDD phase is complete.",
    ),
    PromptKeySpec(
        key="coding.tdd.advanced",
        area=AREA,
        title="TDD progress: phase advanced",
        seed="TDD cycle advanced to phase {phase_number}/{phase_total}: {phase_title}. {phase_instructions}",
        placeholders=frozenset({"phase_instructions", "phase_number", "phase_title", "phase_total"}),
        description="Injected when the TDD cycle moves to the next phase.",
    ),
    PromptKeySpec(
        key="coding.change.verify_sentence.contract",
        area=AREA,
        title="Code change: completion sentence (verification contract)",
        seed=(
            "The change is COMPLETE when `run_validation_commands` reports `all_green=true` for the approved "
            "verification contract ({command_lines}). Where a test framework exists, additionally write or extend "
            "focused tests for the change."
        ),
        placeholders=frozenset({"command_lines"}),
        risk=RISK_HIGH,
        description=(
            "Completion gate sentence when an approved verification contract exists ({command_lines}: its "
            "commands)."
        ),
    ),
    PromptKeySpec(
        key="coding.change.instructions.contract",
        area=AREA,
        title="Code change: step instructions (verification contract)",
        seed=(
            "Inspect the repository briefly, implement the approved change with structured workspace tools, then run "
            "`run_validation_commands` and keep iterating until it reports `all_green=true`. Do not keep gathering "
            "evidence once the affected files are known — move to editing. The verification contract is the completion "
            "gate; raw shell reruns of the same commands are redundant."
        ),
        risk=RISK_HIGH,
        description="Instructions of the Implement And Verify Change step under an approved verification contract.",
    ),
    PromptKeySpec(
        key="coding.change.success.contract",
        area=AREA,
        title="Code change: success criteria (verification contract)",
        seed="The approved change is implemented and `run_validation_commands` reports all_green=true.",
        description="Success criteria of the Implement And Verify Change step under a verification contract.",
    ),
    PromptKeySpec(
        key="coding.change.verify_sentence.tdd",
        area=AREA,
        title="Code change: completion sentence (TDD)",
        seed=(
            "Stay inside the bounded TDD cycle: capture the failing or baseline test state, make the requested change, "
            "and finish only after `run_test_suite` reports `all_green=true`."
        ),
        risk=RISK_HIGH,
        description="Completion gate sentence of a plain TDD coding run.",
    ),
    PromptKeySpec(
        key="coding.change.instructions.tdd",
        area=AREA,
        title="Code change: step instructions (TDD)",
        seed=(
            "Inspect the repository first, update focused tests and implementation with structured workspace tools, "
            "and keep iterating until `run_test_suite` returns `all_green=true`. If inspection shows only scaffold "
            "files or no matching code yet, create the minimal tests and implementation yourself instead of repeating "
            "repository intelligence. Use repository intelligence before broad edits and avoid raw shell test reruns."
        ),
        risk=RISK_HIGH,
        description="Instructions of the Implement And Verify Change step of a plain TDD coding run.",
    ),
    PromptKeySpec(
        key="coding.change.success.tdd",
        area=AREA,
        title="Code change: success criteria (TDD)",
        seed="The requested code change is implemented and `run_test_suite` finishes green.",
        description="Success criteria of the Implement And Verify Change step of a plain TDD coding run.",
    ),
    PromptKeySpec(
        key="coding.tdd.phase.verify_contract",
        area=AREA,
        title="TDD phase instructions: Implement And Verify Contract",
        seed=(
            "Implement the approved change with structured workspace tools, then run `run_validation_commands`. This "
            "phase completes only when it reports `all_green=true`. If the workspace already satisfies the contract, "
            "run `run_validation_commands` anyway — a no-op claim must be proven."
        ),
        risk=RISK_HIGH,
        description="Instructions of the single verify_contract phase under an approved verification contract.",
    ),
    PromptKeySpec(
        key="coding.delivery.instructions",
        area=AREA,
        title="Deliver Change: step instructions",
        seed=(
            "The change is verified. Deliver it: 1) call `commit_and_push_repository_branch` with local_path='.' and "
            "the approved branch from the change units (a no_changes result is fine when everything is already "
            "committed). 2) call `create_bitbucket_pull_request` from that branch into the default branch with a title "
            "referencing the source ticket and a description summarizing the change and the validation result. 3) call "
            "`add_jira_comment` on the source ticket with the branch, the pull request reference, and the validation "
            "result. The platform appends the run's usage metrics to the ticket comment automatically - do not add "
            "your own token or cost figures. Do not edit files and do not re-run validation in this step."
        ),
        risk=RISK_HIGH,
        description="Instructions of the Deliver Change step of governed coding runs.",
    ),
    PromptKeySpec(
        key="coding.delivery.success",
        area=AREA,
        title="Deliver Change: success criteria",
        seed="The branch is pushed, a pull request exists, and the source ticket carries a delivery comment.",
        description="Success criteria of the Deliver Change step.",
    ),
    PromptKeySpec(
        key="coding.change.agent_prompt",
        area=AREA,
        title="Code Change TDD agent prompt",
        seed=(
            "You are the Code Change TDD agent for '{topic}'. Use repository intelligence and structured workspace "
            "editing tools to implement the requested change. {verify_sentence} If the workspace is a freshly "
            "bootstrapped scaffold with only starter files like README.md or .gitignore, stop reconnaissance early and "
            "author the minimal focused tests and implementation files directly. Do not use `run_cli_command` for "
            "duplicate raw test reruns when the verification tools already provide the result."
        ),
        placeholders=frozenset({"topic", "verify_sentence"}),
        risk=RISK_HIGH,
        description=(
            "Prompt of the Code Change TDD agent ({topic}: workflow topic, {verify_sentence}: the completion "
            "sentence)."
        ),
    ),
)
