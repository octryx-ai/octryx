"""Seeds of the fixed report answers: the coding and migration completion reports, the governed pull
request description, the read-only sub-agent wrap-up and the Jira sprint bundle report.

Collected into ``seeds/answer.py`` (``SPECS``); the only code copy of these texts.
"""

from __future__ import annotations

from ..contract import RISK_HIGH, PromptKeySpec

AREA = "answer"

SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="answer.coding.completed",
        area=AREA,
        title="Coding completion: header",
        seed="Implemented the requested coding change and verified it successfully.",
    ),
    PromptKeySpec(
        key="answer.coding.updated_files",
        area=AREA,
        title="Coding completion: updated files label",
        seed="Updated files:",
    ),
    PromptKeySpec(
        key="answer.coding.verification",
        area=AREA,
        title="Coding completion: verification label",
        seed="Verification:",
    ),
    PromptKeySpec(
        key="answer.coding.test_command",
        area=AREA,
        title="Coding completion: test command line",
        seed="- `{command_text}`",
        placeholders=frozenset({"command_text"}),
    ),
    PromptKeySpec(
        key="answer.coding.test_counts",
        area=AREA,
        title="Coding completion: test counts",
        seed=(
            "- Passed: {passed}\n"
            "- Failed: {failed}\n"
            "- Errors: {errors}"
        ),
        placeholders=frozenset({"errors", "failed", "passed"}),
    ),
    PromptKeySpec(
        key="answer.coding.verification_command",
        area=AREA,
        title="Coding completion: verification command line",
        seed="- `{command_text}` exited with code 0",
        placeholders=frozenset({"command_text"}),
    ),
    PromptKeySpec(
        key="answer.child_wrapup.summary",
        area=AREA,
        title="Read-only sub-agent wrap-up: summary",
        seed=(
            "Read-only sub-agent evidence budget reached.\n"
            "\n"
            "Scope:\n"
            "- {scope}\n"
            "\n"
            "Evidence collected:\n"
            "- Successful tool calls: {tool_count}."
        ),
        placeholders=frozenset({"scope", "tool_count"}),
        description="Answer a read-only child returns to its parent.",
    ),
    PromptKeySpec(
        key="answer.child_wrapup.tools",
        area=AREA,
        title="Read-only sub-agent wrap-up: tools line",
        seed="- Tools used: {tool_names}.",
        placeholders=frozenset({"tool_names"}),
    ),
    PromptKeySpec(
        key="answer.child_wrapup.paths_header",
        area=AREA,
        title="Read-only sub-agent wrap-up: paths header",
        seed="- Relevant paths observed:",
    ),
    PromptKeySpec(
        key="answer.child_wrapup.closing",
        area=AREA,
        title="Read-only sub-agent wrap-up: hand-over",
        seed=(
            "No files were edited by this child. Parent must consolidate this evidence, apply migration changes, and "
            "run OpenRewrite, Maven validation, and diff hygiene gates."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="answer.delivery.commit_default_key",
        area=AREA,
        title="Governed delivery: commit key fallback",
        seed="work item",
    ),
    PromptKeySpec(
        key="answer.delivery.commit_default_title",
        area=AREA,
        title="Governed delivery: commit title fallback",
        seed="apply governed coding changes",
    ),
    PromptKeySpec(
        key="answer.delivery.pr_header",
        area=AREA,
        title="Governed delivery: PR description header",
        seed="Octryx governed coding change.",
    ),
    PromptKeySpec(
        key="answer.delivery.pr_commit",
        area=AREA,
        title="Governed delivery: PR commit line",
        seed="Commit: {head_commit}",
        placeholders=frozenset({"head_commit"}),
    ),
    PromptKeySpec(
        key="answer.delivery.pr_source",
        area=AREA,
        title="Governed delivery: PR source line",
        seed="Source: {source_url}",
        placeholders=frozenset({"source_url"}),
    ),
    PromptKeySpec(
        key="answer.delivery.pr_validation",
        area=AREA,
        title="Governed delivery: PR validation",
        seed=(
            "Validation:\n"
            "- git diff --check executed locally before commit."
        ),
    ),
    PromptKeySpec(
        key="answer.jira_bundle.project",
        area=AREA,
        title="Jira sprint bundle: project",
        seed="Jira project: `{project_key}`",
        placeholders=frozenset({"project_key"}),
    ),
    PromptKeySpec(
        key="answer.jira_bundle.release",
        area=AREA,
        title="Jira sprint bundle: release",
        seed="Release: `{release_name}`",
        placeholders=frozenset({"release_name"}),
    ),
    PromptKeySpec(
        key="answer.jira_bundle.release_prepared",
        area=AREA,
        title="Jira sprint bundle: release prepared",
        seed="Release prepared",
    ),
    PromptKeySpec(
        key="answer.jira_bundle.release_version",
        area=AREA,
        title="Jira sprint bundle: release version",
        seed=" (version `{version_id}`)",
        placeholders=frozenset({"version_id"}),
    ),
    PromptKeySpec(
        key="answer.jira_bundle.release_date",
        area=AREA,
        title="Jira sprint bundle: release date",
        seed=", release date `{release_date}`",
        placeholders=frozenset({"release_date"}),
    ),
    PromptKeySpec(
        key="answer.jira_bundle.sprint",
        area=AREA,
        title="Jira sprint bundle: sprint",
        seed="Sprint: `{sprint_name}`",
        placeholders=frozenset({"sprint_name"}),
    ),
    PromptKeySpec(
        key="answer.jira_bundle.sprint_prepared",
        area=AREA,
        title="Jira sprint bundle: sprint prepared",
        seed="Sprint prepared",
    ),
    PromptKeySpec(
        key="answer.jira_bundle.sprint_id",
        area=AREA,
        title="Jira sprint bundle: sprint id",
        seed=" (ID `{sprint_id}`)",
        placeholders=frozenset({"sprint_id"}),
    ),
    PromptKeySpec(
        key="answer.jira_bundle.sprint_board",
        area=AREA,
        title="Jira sprint bundle: board",
        seed=" on board `{board_id}`",
        placeholders=frozenset({"board_id"}),
    ),
    PromptKeySpec(
        key="answer.jira_bundle.assignee",
        area=AREA,
        title="Jira sprint bundle: assignee",
        seed="Assignee used: `{assignee}`",
        placeholders=frozenset({"assignee"}),
    ),
    PromptKeySpec(
        key="answer.jira_bundle.created_header",
        area=AREA,
        title="Jira sprint bundle: created header",
        seed="Created tickets:",
    ),
    PromptKeySpec(
        key="answer.jira_bundle.updated",
        area=AREA,
        title="Jira sprint bundle: updated tickets",
        seed="Updated tickets: {ticket_ids}",
        placeholders=frozenset({"ticket_ids"}),
    ),
    PromptKeySpec(
        key="answer.jira_bundle.assigned",
        area=AREA,
        title="Jira sprint bundle: assigned tickets",
        seed="Assigned to sprint: {ticket_ids}",
        placeholders=frozenset({"ticket_ids"}),
    ),
    PromptKeySpec(
        key="answer.jira_bundle.references_header",
        area=AREA,
        title="Jira sprint bundle: references header",
        seed="Embedded references:",
    ),
)
