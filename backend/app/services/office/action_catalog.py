"""Office file actions: which actions a file type offers, and their chat texts.

An action's id, label and description are UI metadata and stay here. The text an action sends to
the chat (``prompt`` or ``tool_plan`` mode) is agent-facing and comes from the prompt catalog
(``office.file_action.<id>.prompt`` / ``.tool_plan``, seeds in ``prompt_catalog/seeds/office.py``),
rendered through the bound prompt set.
"""

from __future__ import annotations

from pathlib import Path

from ..prompt_catalog import render_prompt

OFFICE_ACTION_MODES = {"prompt", "tool_plan"}

_SHARED_ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("summary", "Summarize file", "Summarize content, structure and key takeaways."),
    ("issues", "Check issues", "Review formatting, structure and quality problems."),
)
_ACTIONS_BY_TYPE: dict[str, tuple[tuple[str, str, str], ...]] = {
    "xlsx": (
        ("formulas", "Inspect formulas", "Focus on sheets, totals, formulas and anomalies."),
        ("budget", "Analyze workbook", "Turn the workbook into a management-facing explanation."),
    ),
    "pptx": (
        ("slides", "Summarize slides", "Explain the storyline slide by slide."),
        ("speaker", "Create speaker notes", "Draft concise presenter notes from the slides."),
    ),
    "docx": (
        ("sections", "Extract sections", "Pull out headings, sections and action items."),
        ("forms", "Inspect forms", "Check protection and editable fields."),
    ),
}


def office_action_entries(file_type: str) -> list[dict[str, str]]:
    """The actions a file type offers, without their texts (no prompt set needed)."""
    specific = _ACTIONS_BY_TYPE.get(file_type, _ACTIONS_BY_TYPE["docx"])
    return [
        {"id": action_id, "label": label, "description": description}
        for action_id, label, description in (*_SHARED_ACTIONS, *specific)
    ]


def office_action_text(path: str | Path, action_id: str, mode: str) -> str:
    """The chat text of one action in ``prompt`` or ``tool_plan`` mode, from the bound prompt set."""
    quoted_path = f'"{Path(path)}"'
    if mode == "prompt":
        return render_prompt(f"office.file_action.{action_id}.prompt", quoted_path=quoted_path)
    plan_header = render_prompt("office.file_action.plan_header", quoted_path=quoted_path)
    return render_prompt(f"office.file_action.{action_id}.tool_plan", plan_header=plan_header)


def office_action_catalog(path: str | Path, file_type: str) -> list[dict[str, str]]:
    """Every action of the file type with both of its texts rendered."""
    return [
        {
            **entry,
            "prompt": office_action_text(path, entry["id"], "prompt"),
            "tool_plan": office_action_text(path, entry["id"], "tool_plan"),
        }
        for entry in office_action_entries(file_type)
    ]


def available_office_action_views(file_type: str) -> list[str]:
    if file_type == "docx":
        return ["html", "text", "outline", "annotated", "stats", "issues", "forms"]
    return ["html", "text", "outline", "annotated", "stats", "issues"]
