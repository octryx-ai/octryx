"""``documentation.tree_unchanged``: the read-only pre-push documentation draft left the reviewed change untouched.

Freeze proposal §3.1 and acceptance case 13. ``doc_draft`` lies between the independent review and the push, so the
platform proves, before it pushes, that the working copy is still exactly the tree the reviewer reviewed
(``review.tree``; the same staged-tree hash ``platform/scm.push`` compares). A mismatch is a ``safety`` refusal: the
run ends ``blocked`` (the global ``safety`` class is never relaxed), nothing is pushed. The push itself still checks
the working copy before and the pushed commit's tree after (``scm._reviewed_tree``), so the pushed commit's tree
equals ``review.tree``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....time_utils import utc_now
from .. import safe_git
from ..platform.dispatch import CLASS_SAFETY, FAILED, SUCCEEDED, ToolOutcome
from .s1_graph import set_facts


async def tree_unchanged(db: AsyncSession, run: WorkflowRun) -> ToolOutcome:
    del db
    context = dict(run.context or {})
    reviewed = str(dict(context.get("review") or {}).get("tree") or "")
    local_path = str(context.get("local_path") or "")
    if not reviewed:
        return ToolOutcome(FAILED, reason="no reviewed tree is recorded: the draft cannot be proven to leave the "
                                          "reviewed change untouched", failure_class=CLASS_SAFETY)
    if not local_path:
        return ToolOutcome(FAILED, reason="the run has no working copy on the server to compare with the reviewed "
                                          "tree", failure_class=CLASS_SAFETY)
    current = await safe_git.staged_tree(local_path)
    check = {"reviewed_tree": reviewed, "tree": current, "at": utc_now().isoformat(), "node_id": run.current_node_id}
    set_facts(run, tree_check=check)
    if current != reviewed:
        return ToolOutcome(FAILED, check, "the documentation draft changed the reviewed working copy "
                                          f"(tree {current[:12] or 'unreadable'} is not the reviewed {reviewed[:12]})",
                           failure_class=CLASS_SAFETY)
    return ToolOutcome(SUCCEEDED, check)


__all__ = ["tree_unchanged"]
