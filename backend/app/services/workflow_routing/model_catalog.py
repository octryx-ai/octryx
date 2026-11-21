"""Model-side workflow catalog: compact, bounded list of published definitions.

Progressive disclosure: the model sees a one-liner
catalog of the published workflow definitions every turn and may select one
via the ``select_workflow`` meta tool. The catalog describes, the model
decides, the runtime gates guarantee — there is no intent classifier, and the
user's explicit ``workflow_key`` selection always takes precedence.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..prompt_catalog import render_prompt
from .explicit_selection import list_published_workflow_definitions

# Bounds keep the catalog a cheap constant-size prompt block.
MODEL_WORKFLOW_CATALOG_MAX_ENTRIES = 24
MODEL_WORKFLOW_CATALOG_MAX_ONE_LINER_CHARS = 200
# The system-prompt line is shorter than the entry (the full entries cost 2.4k of a chat request's
# 11.7k system characters). The chat router has already read the full texts before the turn; select_workflow and
# list_available_workflows still return the 200-character entry.
MODEL_WORKFLOW_CATALOG_PROMPT_LINE_CHARS = 120

# Protocol: the loop detects the catalog section by this heading (agent/loops/response/_loop_response_guards.py),
# so it stays fixed; the selection rules under it are the catalog key ``workflow.catalog.rules``.
MODEL_WORKFLOW_CATALOG_PROMPT_MARKER = "## Workflow catalog"


def _bounded_one_liner(value: str, limit: int = MODEL_WORKFLOW_CATALOG_MAX_ONE_LINER_CHARS) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


async def build_model_workflow_catalog(
    db: AsyncSession,
    *,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """Compact catalog entries, deterministically sorted and bounded. What people are not offered is not offered to the
    model either (``run_admission.phased_catalog.hidden_from_people``): a test fixture and a workflow
    a pull request starts (its Start box says so; the PR review bot starts it from a webhook, its sync or a comment)."""
    definitions = await list_published_workflow_definitions(db, project_id=project_id)
    catalog = [
        {
            "workflow_key": str(definition.get("key") or ""),
            "title": str(definition.get("title") or ""),
            "when_to_use": _bounded_one_liner(
                str(definition.get("when_to_use") or definition.get("description") or "")
            ),
            "capability": str(definition.get("capability") or ""),
        }
        for definition in definitions
        if str(definition.get("key") or "").strip()
    ]
    # list_published_workflow_definitions sorts by (key, project_id); keep
    # that deterministic order and apply the hard bound.
    return catalog[:MODEL_WORKFLOW_CATALOG_MAX_ENTRIES]


def render_model_workflow_catalog_prompt(catalog: list[dict[str, Any]]) -> str:
    """Render the catalog as a compact system-prompt section ('' when empty)."""
    entries = [entry for entry in catalog or [] if str(entry.get("workflow_key") or "").strip()]
    if not entries:
        return ""
    lines = [MODEL_WORKFLOW_CATALOG_PROMPT_MARKER, render_prompt("workflow.catalog.rules")]
    for entry in entries:
        capability = str(entry.get("capability") or "").strip()
        capability_suffix = f" [{capability}]" if capability else ""
        lines.append(
            f"- {entry['workflow_key']}{capability_suffix}: "
            f"{_bounded_one_liner(entry.get('when_to_use') or entry.get('title') or '',
                                  MODEL_WORKFLOW_CATALOG_PROMPT_LINE_CHARS)}"
            .rstrip()
        )
    return "\n".join(lines)


__all__ = [
    "MODEL_WORKFLOW_CATALOG_MAX_ENTRIES",
    "MODEL_WORKFLOW_CATALOG_PROMPT_MARKER",
    "MODEL_WORKFLOW_CATALOG_MAX_ONE_LINER_CHARS",
    "MODEL_WORKFLOW_CATALOG_PROMPT_LINE_CHARS",
    "build_model_workflow_catalog",
    "render_model_workflow_catalog_prompt",
]
