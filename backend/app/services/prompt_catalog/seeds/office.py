"""Seeds of the office texts: the corporate identity section, the composer tool messages and the Office file actions."""

from __future__ import annotations

from ..contract import PromptKeySpec

AREA = "office"

SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="office.template.path_not_a_file",
        area=AREA,
        title="Office composer: explicit template_path is not a file",
        seed="template_path '{template_path}' is not a file",
        placeholders=frozenset({"template_path"}),
        description="Tool error of create_presentation and create_document.",
    ),
    PromptKeySpec(
        key="office.template.path_outside_workspace",
        area=AREA,
        title="Office composer: explicit template_path outside the workspace",
        seed=(
            "template_path '{template_path}' is outside the workspace. Use a template file inside the "
            "workspace, or omit template_path to use the corporate identity profile."
        ),
        placeholders=frozenset({"template_path"}),
        description="Tool error: an explicit template must be a file inside the turn's workspace.",
    ),
    PromptKeySpec(
        key="office.template.no_database_session",
        area=AREA,
        title="Office composer: no database session",
        seed=(
            "No database session available to resolve a corporate identity profile; pass template_path "
            "explicitly."
        ),
        description="Tool error outside a turn (no session to read the corporate identity profile).",
    ),
    PromptKeySpec(
        key="office.presentation.evidence_missing",
        area=AREA,
        title="create_presentation: no evidence in the turn",
        seed=(
            "No {snapshot_tool} result and no `content` in this turn. The deck is composed from "
            "collected evidence — run {snapshot_tool} first for an architecture deck, or pass `content` "
            "(title + sourced sections) for any other topic."
        ),
        placeholders=frozenset({"snapshot_tool"}),
        description="Tool result when neither an AWS topology snapshot nor sourced `content` is present.",
    ),
    PromptKeySpec(
        key="office.presentation.composed_with_warnings",
        area=AREA,
        title="create_presentation: composed with gate warnings",
        seed=(
            "Deck composed with {warning_count} quality warning(s) — review quality_findings before "
            "sharing."
        ),
        placeholders=frozenset({"warning_count"}),
        description="Tool result message after composition; {warning_count} is the number of warning findings.",
    ),
    PromptKeySpec(
        key="office.presentation.composed_clean",
        area=AREA,
        title="create_presentation: composed without gate warnings",
        seed="Deck composed; slide gate reported no warnings.",
        description="Tool result message after composition without warning findings.",
    ),
    PromptKeySpec(
        key="office.presentation.corp_identity_template_missing",
        area=AREA,
        title="create_presentation: default profile without a PowerPoint template",
        seed="Corporate identity profile '{profile_id}' has no usable PowerPoint template on disk.",
        placeholders=frozenset({"profile_id"}),
        description=(
            "needs_configuration (corp_identity_template_missing): the chosen profile's template file is "
            "missing."
        ),
    ),
    PromptKeySpec(
        key="office.presentation.template_unconfigured",
        area=AREA,
        title="create_presentation: no template configured",
        seed=(
            "No presentation template is configured: there is no corporate identity profile and the "
            "presentation fallback template is disabled. An administrator uploads a corporate identity "
            "or enables the built-in neutral template in the Corp. Identity tab."
        ),
        description=(
            "needs_configuration (presentation_template_unconfigured): no profile and the fallback is "
            "disabled."
        ),
    ),
    PromptKeySpec(
        key="office.document.evidence_missing",
        area=AREA,
        title="create_document: no evidence in the turn",
        seed=(
            "No {snapshot_tool} result and no `content` in this turn. The document is composed from "
            "collected evidence — run {snapshot_tool} first for an architecture document, or pass "
            "`content` (title + sourced sections) for any other topic."
        ),
        placeholders=frozenset({"snapshot_tool"}),
        description="Tool result when neither an AWS topology snapshot nor sourced `content` is present.",
    ),
    PromptKeySpec(
        key="office.document.template_selection",
        area=AREA,
        title="create_document: choose one of several Word templates",
        seed=(
            "This profile has several Word templates for different purposes. Call create_document again "
            "with `template` set to the template_id or name that fits this document."
        ),
        description="Tool result with status needs_template_selection; the catalog follows in `templates`.",
    ),
    PromptKeySpec(
        key="office.document.template_unconfigured",
        area=AREA,
        title="create_document: no corporate identity profile",
        seed=(
            "No corporate identity profile is available. Upload a Word template as a corporate identity "
            "profile, or pass template_path explicitly."
        ),
        description="needs_configuration (document_template_unconfigured).",
    ),
    PromptKeySpec(
        key="office.document.profile_without_template",
        area=AREA,
        title="create_document: profile without a Word template",
        seed=(
            "Corporate identity profile '{profile_id}' has no Word (.docx/.dotx) template. Upload one, "
            "or pass template_path explicitly."
        ),
        placeholders=frozenset({"profile_id"}),
        description=(
            "needs_configuration (corp_identity_template_missing): the profile holds no .docx/.dotx "
            "template."
        ),
    ),
    PromptKeySpec(
        key="office.document.template_not_found",
        area=AREA,
        title="create_document: named Word template not in the profile",
        seed="No Word template named '{template}' in this profile. Available: {available}",
        placeholders=frozenset({"available", "template"}),
        description="Tool error; {available} lists the profile's template names.",
    ),
    PromptKeySpec(
        key="office.document.composed_with_warnings",
        area=AREA,
        title="create_document: composed with quality warnings",
        seed="Document composed with {warning_count} quality warning(s) — review before sharing.",
        placeholders=frozenset({"warning_count"}),
        description="Tool result message after composition; {warning_count} is the number of warning findings.",
    ),
    PromptKeySpec(
        key="office.document.composed_clean",
        area=AREA,
        title="create_document: composed without quality warnings",
        seed="Document composed; no quality warnings.",
        description="Tool result message after composition without warning findings.",
    ),
    PromptKeySpec(
        key="office.file_action.plan_header",
        area=AREA,
        title="Office file action: tool-plan header",
        seed=(
            "Use Office tools for the file at {quoted_path}. Work in this order: 1. inspect the most "
            "relevant Office views, 2. summarize findings crisply, 3. call out issues or follow-up "
            "actions only if supported by the file."
        ),
        placeholders=frozenset({"quoted_path"}),
        description="First line of every Office file action tool plan; {quoted_path} is the quoted file path.",
    ),
    PromptKeySpec(
        key="office.file_action.summary.prompt",
        area=AREA,
        title="Office file action 'Summarize file': prompt",
        seed=(
            "Read the Office file at {quoted_path} and summarize its contents, structure, key findings, "
            "and any noteworthy issues."
        ),
        placeholders=frozenset({"quoted_path"}),
        description="The chat message the action sends in prompt mode; {quoted_path} is the quoted file path.",
    ),
    PromptKeySpec(
        key="office.file_action.summary.tool_plan",
        area=AREA,
        title="Office file action 'Summarize file': tool plan",
        seed=(
            "{plan_header}\n"
            "Focus: produce a concise file summary.\n"
            "Preferred views: text, outline, stats.\n"
            "Output: contents, structure, key findings, noteworthy issues."
        ),
        placeholders=frozenset({"plan_header"}),
        description=(
            "The chat message the action sends in tool_plan mode; {plan_header} is "
            "office.file_action.plan_header."
        ),
    ),
    PromptKeySpec(
        key="office.file_action.issues.prompt",
        area=AREA,
        title="Office file action 'Check issues': prompt",
        seed=(
            "Inspect the Office file at {quoted_path} for formatting, structure, quality, and "
            "consistency issues. Explain the most important findings and suggested fixes."
        ),
        placeholders=frozenset({"quoted_path"}),
        description="The chat message the action sends in prompt mode; {quoted_path} is the quoted file path.",
    ),
    PromptKeySpec(
        key="office.file_action.issues.tool_plan",
        area=AREA,
        title="Office file action 'Check issues': tool plan",
        seed=(
            "{plan_header}\n"
            "Focus: quality and issue review.\n"
            "Preferred views: issues, stats, annotated.\n"
            "Output: top issues, why they matter, and suggested fixes."
        ),
        placeholders=frozenset({"plan_header"}),
        description=(
            "The chat message the action sends in tool_plan mode; {plan_header} is "
            "office.file_action.plan_header."
        ),
    ),
    PromptKeySpec(
        key="office.file_action.formulas.prompt",
        area=AREA,
        title="Office file action 'Inspect formulas': prompt",
        seed=(
            "Inspect the spreadsheet at {quoted_path}. Focus on workbook structure, sheets, formulas, "
            "totals, anomalies, and the most important numeric signals."
        ),
        placeholders=frozenset({"quoted_path"}),
        description="The chat message the action sends in prompt mode; {quoted_path} is the quoted file path.",
    ),
    PromptKeySpec(
        key="office.file_action.formulas.tool_plan",
        area=AREA,
        title="Office file action 'Inspect formulas': tool plan",
        seed=(
            "{plan_header}\n"
            "Focus: spreadsheet logic and formulas.\n"
            "Preferred views: outline, stats, annotated, text.\n"
            "Output: sheet structure, important formulas, totals, anomalies, and numeric signals."
        ),
        placeholders=frozenset({"plan_header"}),
        description=(
            "The chat message the action sends in tool_plan mode; {plan_header} is "
            "office.file_action.plan_header."
        ),
    ),
    PromptKeySpec(
        key="office.file_action.budget.prompt",
        area=AREA,
        title="Office file action 'Analyze workbook': prompt",
        seed=(
            "Read the spreadsheet at {quoted_path} and explain it sheet by sheet. Highlight the main "
            "metrics, trends, formulas, and any risks or inconsistencies."
        ),
        placeholders=frozenset({"quoted_path"}),
        description="The chat message the action sends in prompt mode; {quoted_path} is the quoted file path.",
    ),
    PromptKeySpec(
        key="office.file_action.budget.tool_plan",
        area=AREA,
        title="Office file action 'Analyze workbook': tool plan",
        seed=(
            "{plan_header}\n"
            "Focus: management-facing workbook explanation.\n"
            "Preferred views: text, outline, stats.\n"
            "Output: sheet-by-sheet explanation, main metrics, trends, formulas, risks, inconsistencies."
        ),
        placeholders=frozenset({"plan_header"}),
        description=(
            "The chat message the action sends in tool_plan mode; {plan_header} is "
            "office.file_action.plan_header."
        ),
    ),
    PromptKeySpec(
        key="office.file_action.slides.prompt",
        area=AREA,
        title="Office file action 'Summarize slides': prompt",
        seed=(
            "Read the presentation at {quoted_path} and summarize it slide by slide. Explain the "
            "storyline, key messages, and presentation quality."
        ),
        placeholders=frozenset({"quoted_path"}),
        description="The chat message the action sends in prompt mode; {quoted_path} is the quoted file path.",
    ),
    PromptKeySpec(
        key="office.file_action.slides.tool_plan",
        area=AREA,
        title="Office file action 'Summarize slides': tool plan",
        seed=(
            "{plan_header}\n"
            "Focus: slide-by-slide storyline.\n"
            "Preferred views: text, outline, annotated, stats.\n"
            "Output: storyline, key messages per slide, and presentation quality."
        ),
        placeholders=frozenset({"plan_header"}),
        description=(
            "The chat message the action sends in tool_plan mode; {plan_header} is "
            "office.file_action.plan_header."
        ),
    ),
    PromptKeySpec(
        key="office.file_action.speaker.prompt",
        area=AREA,
        title="Office file action 'Create speaker notes': prompt",
        seed=(
            "Read the presentation at {quoted_path} and draft concise speaker notes for each slide, "
            "including the main message and recommended talking points."
        ),
        placeholders=frozenset({"quoted_path"}),
        description="The chat message the action sends in prompt mode; {quoted_path} is the quoted file path.",
    ),
    PromptKeySpec(
        key="office.file_action.speaker.tool_plan",
        area=AREA,
        title="Office file action 'Create speaker notes': tool plan",
        seed=(
            "{plan_header}\n"
            "Focus: speaker notes.\n"
            "Preferred views: text, annotated, outline.\n"
            "Output: concise notes per slide with main message and talking points."
        ),
        placeholders=frozenset({"plan_header"}),
        description=(
            "The chat message the action sends in tool_plan mode; {plan_header} is "
            "office.file_action.plan_header."
        ),
    ),
    PromptKeySpec(
        key="office.file_action.sections.prompt",
        area=AREA,
        title="Office file action 'Extract sections': prompt",
        seed=(
            "Read the document at {quoted_path} and extract the main headings, sections, decisions, "
            "action items, and open questions."
        ),
        placeholders=frozenset({"quoted_path"}),
        description="The chat message the action sends in prompt mode; {quoted_path} is the quoted file path.",
    ),
    PromptKeySpec(
        key="office.file_action.sections.tool_plan",
        area=AREA,
        title="Office file action 'Extract sections': tool plan",
        seed=(
            "{plan_header}\n"
            "Focus: document structure extraction.\n"
            "Preferred views: outline, text, annotated.\n"
            "Output: headings, sections, decisions, action items, open questions."
        ),
        placeholders=frozenset({"plan_header"}),
        description=(
            "The chat message the action sends in tool_plan mode; {plan_header} is "
            "office.file_action.plan_header."
        ),
    ),
    PromptKeySpec(
        key="office.file_action.forms.prompt",
        area=AREA,
        title="Office file action 'Inspect forms': prompt",
        seed=(
            "Inspect the document at {quoted_path} for forms, protection, editable fields, and any "
            "document workflow constraints."
        ),
        placeholders=frozenset({"quoted_path"}),
        description="The chat message the action sends in prompt mode; {quoted_path} is the quoted file path.",
    ),
    PromptKeySpec(
        key="office.file_action.forms.tool_plan",
        area=AREA,
        title="Office file action 'Inspect forms': tool plan",
        seed=(
            "{plan_header}\n"
            "Focus: forms and workflow constraints.\n"
            "Preferred views: forms, stats, issues.\n"
            "Output: protection state, editable fields, workflow constraints, and relevant risks."
        ),
        placeholders=frozenset({"plan_header"}),
        description=(
            "The chat message the action sends in tool_plan mode; {plan_header} is "
            "office.file_action.plan_header."
        ),
    ),
)
