"""The code style of a changing phase, and its check at the phase's Stop."""

from __future__ import annotations

from typing import Any

from ...workflow_checks.library import FAILED, PASSED, CheckResult

MAX_LISTED = 12
CHANGING = ("change", "deliver")


async def phase_style(db: Any, run: Any, capability_class: str) -> dict[str, Any] | None:
    if capability_class not in CHANGING or not run.project_id:
        return None
    from ....models import Project
    from ...code_style.resolve import effective, flat
    from ...code_style.store import levels
    from ..platform.repo_ref import _record, parse_repository

    ref = parse_repository(run.repository)
    record = await _record(db, run, ref) if ref is not None else None
    stored = await levels(db, project=await db.get(Project, run.project_id), record=record)
    named = {name for level in stored.values() for name in dict(level.get("languages") or {})}
    from ...code_style.defaults import BUILT_IN

    named |= set(BUILT_IN["languages"])
    return {"general": flat(effective(stored, None)),
            "languages": {name: flat(effective(stored, name)) for name in sorted(named)}}


STYLE_CHECK = "code_style"


def style_result(style: dict[str, Any] | None, sizes: Any, tools: Any = None,
                 l10n: Any = None, diagrams: Any = None) -> CheckResult | None:
    from app.services.code_style.l10n_check import l10n_findings
    from app.services.code_style.tool_check import tool_findings

    from ...code_style.check import findings
    from ...code_style.diagrams import diagram_findings

    if not style:
        return None
    found = [*findings(style, sizes), *tool_findings(tools, style), *l10n_findings(style, l10n),
             *diagram_findings(style, diagrams)]
    errors = [item.text() for item in found if item.severity == "error"]
    warnings = [item.text() for item in found if item.severity == "warning"]
    if not errors and not warnings:
        return None
    listed = errors[:MAX_LISTED] + ([f"and {len(errors) - MAX_LISTED} more"] if len(errors) > MAX_LISTED else [])
    note = ("Warnings (not blocking): " + "; ".join(warnings[:MAX_LISTED])) if warnings else ""
    if not errors:
        return CheckResult(type=STYLE_CHECK, outcome=PASSED, blocking=False,
                           description="Code style of the installation", detail=note)
    return CheckResult(type=STYLE_CHECK, outcome=FAILED, blocking=True,
                       description="Code style of the installation: " + "; ".join(listed), detail=note)


__all__ = ["STYLE_CHECK", "phase_style", "style_result"]
