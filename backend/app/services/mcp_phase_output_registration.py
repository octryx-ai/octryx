"""The phase output tools on the Knowledge MCP server (``workflow_runs/phase_outputs``).

A run phase submits its structured artefact over MCP exactly as in chat; the handlers live in
``mcp_workflow_run_tools`` behind ``mcp_parity_dispatch`` (scope ``workflow:execute``, which a device grant holds).
A refusal raises :class:`ToolError`, so the session's recorded tool call is an error and never counts as a
``tool_called`` check.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from .lenient_arguments import criteria_from_lines, structured

Call = Callable[[Context | None, str, dict[str, Any]], Awaitable[dict[str, Any]]]


def _recorded(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("state") != "recorded":
        raise ToolError(f"{result.get('reason') or result.get('state')}: {result.get('message') or ''}".strip())
    return result


def register_phase_output_tools(server: FastMCP, call: Call, *, workspace_note: str) -> None:
    @server.tool(
        description=(
            "Workflow run triage phase only: record the run's Work item's Definition of Ready. type is feature, "
            "bug, task or incident (it selects the follow-up workflow); a feature names its acceptance criteria, a "
            "bug its reproduction steps and the expected and actual behaviour; name the affected repository as "
            "provider:owner/repo; list every open question. The server decides whether the item is ready."
            + workspace_note
        )
    )
    async def submit_definition_of_ready(
        type: str, summary: str, acceptance_criteria: list[str] | str | None = None,
        reproduction_steps: list[str] | str | None = None, expected: str | None = None, actual: str | None = None,
        repository: str | None = None, open_questions: list[str] | str | None = None, ctx: Context | None = None,
    ) -> dict[str, Any]:
        return _recorded(await call(ctx, "submit_definition_of_ready", {
            "type": type, "summary": summary,
            "acceptance_criteria": structured(acceptance_criteria, name="acceptance_criteria"),
            "reproduction_steps": structured(reproduction_steps, name="reproduction_steps"), "expected": expected,
            "actual": actual, "repository": repository,
            "open_questions": structured(open_questions, name="open_questions")}))

    @server.tool(
        description=(
            "Workflow run phase that proposes the test contract only (e.g. Clarify): submit it as data, never as "
            "chat text. criteria is a list of {id, text, tests, command} — tests are {id, role} with the test's node "
            "id (file path, class, name: tests/test_totals.py::test_rounds_half_up) and role new (new behaviour: "
            "fails before the change — on an assertion, or at its import while the code is new — passes after it) or "
            "regression (an existing test that must "
            "keep passing); a test the branch already passes cannot be new; command runs them — or {id, text, "
            "manual_only: true, manual_reason} for a criterion no test can prove. Simpler and equivalent: "
            "criteria_lines, one string per criterion 'id | text | command | test ids' (test ids comma separated, "
            "'(regression)' after a regression test; command 'manual: <reason>' for a manual criterion); send "
            "criteria or criteria_lines. The server records it and "
            "drafts the Work item's change plan from it for the user to confirm; nothing else needs write "
            "rights. A refusal lists what to fix." + workspace_note
        )
    )
    async def submit_test_contract(
        criteria: list[dict[str, Any]] | str | None = None, summary: str | None = None,
        open_questions: list[str] | str | None = None, criteria_lines: list[str] | str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        # Gemma via Bedrock mangles lists of objects: criteria_lines is the flat form; a list sent
        # as text in Gemma's notation is read back (lenient_arguments).
        given = criteria_from_lines(criteria_lines) if criteria_lines else structured(criteria, name="criteria")
        return _recorded(await call(ctx, "submit_test_contract", {
            "criteria": given or [], "summary": summary,
            "open_questions": structured(open_questions, name="open_questions")}))

    @server.tool(
        description=(
            "Workflow run reproduce phase only: after running the tests, submit the test ids that reproduce the "
            "bug (node ids: path/to/test_file.py::test_name) and the symptom they show. The user confirms them "
            "against the tests the platform saw failing." + workspace_note
        )
    )
    async def submit_reproduction(
        tests: list[str] | str, symptom: str, steps: list[str] | str | None = None,
        explanation: str | None = None, ctx: Context | None = None,
    ) -> dict[str, Any]:
        return _recorded(await call(ctx, "submit_reproduction", {
            "tests": structured(tests, name="tests"), "symptom": symptom, "steps": structured(steps, name="steps"),
            "explanation": explanation}))

    @server.tool(
        description=(
            "Workflow run hypothesis phase only: submit the incident's most likely cause, impact, next step, "
            "whether a code fix is needed, and the sources (URLs or citations of the evidence read) it rests on. "
            "It becomes the bug ticket's text if the user opens one." + workspace_note
        )
    )
    async def submit_incident_hypothesis(
        summary: str, cause: str, impact: str, next_step: str, code_fix_needed: bool, sources: list[str],
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return _recorded(await call(ctx, "submit_incident_hypothesis", {
            "summary": summary, "cause": cause, "impact": impact, "next_step": next_step,
            "code_fix_needed": code_fix_needed, "sources": sources}))

    @server.tool(
        description=(
            "Workflow run documentation phase only: submit the feature documentation as data — title, what the "
            "feature does, why it exists, how to use it (notes optional). Prose only: the server adds the confirmed "
            "acceptance criteria with their tests and the ticket and pull request links; the user confirms the page "
            "and the platform publishes it." + workspace_note
        )
    )
    async def submit_feature_documentation(
        title: str, what: str, why: str, how_to_use: str, notes: str | None = None, ctx: Context | None = None,
    ) -> dict[str, Any]:
        return _recorded(await call(ctx, "submit_feature_documentation", {
            "title": title, "what": what, "why": why, "how_to_use": how_to_use, "notes": notes}))

    @server.tool(
        description=(
            "Workflow run phase that plans the work only (the coordinator): split the story into items agents "
            "build at the same time. contract: the shared interface every item follows (API shapes, component "
            "names, test ids). items: a list of {id, title, role, model?, depends_on, paths, appends_to?, "
            "instructions, "
            "proofs, reopen?} — id lower case letters, digits and '-'; role one of the workflow's roles; depends_on "
            "the ids it needs merged first; paths the relative globs only this item changes (items that can run at "
            "the same time may not share any); appends_to shared files an item it depends on owns, where it only "
            "adds its entries; proofs the test ids under its own paths that show it works; reopen true sends a "
            "merged item back "
            "to work. Every problem is listed at once; while the items run a revised plan may not change a running "
            "item." + workspace_note
        )
    )
    async def submit_work_plan(contract: str, items: list[dict[str, Any]] | str, ctx: Context | None = None
                               ) -> dict[str, Any]:
        return _recorded(await call(ctx, "submit_work_plan", {"contract": contract,
                                                              "items": structured(items, name="items") or []}))

    @server.tool(
        description=(
            "Workflow run phase that splits an epic into stories only: submit the stories in build order. stories is "
            "a list of {title, goal, criteria, spec_sections, depends_on_titles}: a unique title, the story's goal, "
            "at least one acceptance criterion, the spec sections it builds, and the titles of earlier stories it "
            "depends on. The platform creates the stories under the epic; a refusal lists what to fix."
            + workspace_note
        )
    )
    async def submit_story_plan(stories: list[dict[str, Any]] | str, ctx: Context | None = None) -> dict[str, Any]:
        return _recorded(await call(ctx, "submit_story_plan", {"stories": structured(stories, name="stories") or []}))

    from ..tools.definitions.workflow_outputs import SPEC_STUDIO_DESCRIPTION

    @server.tool(description=SPEC_STUDIO_DESCRIPTION + workspace_note)
    async def submit_spec_studio(
        title: str, screens: list[dict[str, Any]] | str, spec_mode: str | None = None, target: str | None = None,
        summary: str | None = None, spec_path: str | None = None, language: str | None = None,
        out_of_scope: list[str] | str | None = None, stories: list[dict[str, Any]] | str | None = None,
        design: dict[str, Any] | str | None = None, nav: list[dict[str, Any]] | str | None = None,
        questions: list[dict[str, Any]] | str | None = None, rules: list[dict[str, Any]] | str | None = None,
        acceptance: list[dict[str, Any]] | str | None = None, requirements: list[dict[str, Any]] | str | None = None,
        glossary: list[dict[str, Any]] | str | None = None, conditions: list[dict[str, Any]] | str | None = None,
        flow: dict[str, Any] | str | None = None, ctx: Context | None = None,
    ) -> dict[str, Any]:
        loose = {"screens": screens, "out_of_scope": out_of_scope, "stories": stories, "design": design, "nav": nav,
                 "questions": questions, "rules": rules, "acceptance": acceptance, "requirements": requirements,
                 "glossary": glossary, "conditions": conditions, "flow": flow}
        return _recorded(await call(ctx, "submit_spec_studio", {
            "title": title, "spec_mode": spec_mode, "target": target, "summary": summary, "spec_path": spec_path,
            "language": language, **{key: structured(value, name=key, kind=dict if key in ("design", "flow") else list)
               for key, value in loose.items()}}))

    @server.tool(
        description=(
            "Workflow run phase that declares its possible results only: record the result the phase ends with — "
            "value is exactly one of the results its contract lists — and a one-line summary of why. The phase is "
            "done only once a result is recorded; a following condition routes on it." + workspace_note
        )
    )
    async def submit_phase_result(value: str, summary: str | None = None, ctx: Context | None = None
                                  ) -> dict[str, Any]:
        return _recorded(await call(ctx, "submit_phase_result", {"value": value, "summary": summary}))


__all__ = ["register_phase_output_tools"]
