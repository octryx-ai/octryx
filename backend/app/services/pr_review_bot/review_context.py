"""Everything the bot gives its reviewer besides the diff (stage E), gathered in ``pr_review.prepare``:

- the pull request's ticket and its acceptance criteria (``ticket_context``);
- the specification sections and linked Confluence pages (``spec_context``);
- the code graph's callers of the changed symbols and the authoring run's confirmed criteria (``graph_context``).

Each adds fenced context sections to the run and returns its facts for the summary's footer.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun


async def gather(db: AsyncSession, run: WorkflowRun, facts: dict[str, Any], root: str, base: str,
                 head: str) -> dict[str, Any]:
    from .graph_context import authoring_run, code_graph
    from .spec_context import spec_context
    from .ticket_context import link_ticket

    found = {"ticket": await link_ticket(db, run, facts, root, base, head),
             "spec": await spec_context(db, run, root, base, head),
             "graph": await code_graph(db, run, root, base, head)}
    if facts.get("authored_by_run"):
        found["author"] = await authoring_run(db, run, str(facts["authored_by_run"]))
    found["triage"] = await _triage(db, run, root, base, head)
    return found


async def _triage(db: AsyncSession, run: WorkflowRun, root: str, base: str, head: str) -> dict[str, Any]:
    """How to read the change (``triage``, F1): the reviewer's guide, the mechanical files left out of its diff,
    the size brake's note."""
    from ..workflow_runs.octryx.code_limits import phase_style
    from .settings import repository_record, settings_of
    from .triage import MECHANICAL, classify, reading_section, size_note

    if not root or not base:
        return {}
    files = await classify(root, base, head, await phase_style(db, run, "change") or {})
    if not files:
        return {}
    settings = settings_of(await repository_record(db, str(run.project_id), str(run.repository)))
    context = dict(run.context or {})
    context["review_summarized_paths"] = [{"path": item.path, **({"old": item.old} if item.old else {})}
                                          for item in files if item.kind == MECHANICAL]
    context["review_context_sections"] = [
        {"title": "how to read this change", "text": reading_section(files)},
        *(context.get("review_context_sections") or [])]  # first: it frames everything after it
    run.context = context
    from .hotspots import hotspots, section

    records = [item.to_dict() for item in files]
    spots = await hotspots(root, base, head, records, settings.hotspot_paths)
    if spots:  # right after the reading guide: where to look first (F2)
        context = dict(run.context or {})
        sections = list(context.get("review_context_sections") or [])
        sections.insert(1, {"title": "look closely here first (hotspots, with the reason)", "text": section(spots)})
        context["review_context_sections"] = sections
        run.context = context
    return {"files": records, "size_note": size_note(files, settings.size_limit_lines, settings.size_limit_files),
            "hotspots": [spot.to_dict() for spot in spots]}


__all__ = ["gather"]
