"""Seeds of the coding prompts: TDD phases and reminders and the coding-change workflow agent."""

from __future__ import annotations

from ..contract import PromptKeySpec

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
)
