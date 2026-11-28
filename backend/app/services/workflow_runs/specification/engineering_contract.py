"""Project freshly authorized accepted-spec criteria for an engineering test contract."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ....models import User, WorkflowRun
from ..records import WorkflowRunError


async def accepted_spec_criteria(db, run: WorkflowRun, *, principal: User | None = None) -> dict[str, Any] | None:
    # Missing authority raises: callers must refuse without replacing the recorded contract.
    from ..handoff.specification import has_spec_handoff, resolve_accepted_spec

    if not await has_spec_handoff(db, run):
        return None
    snapshot = await resolve_accepted_spec(db, run, principal=principal)
    envelope = snapshot["envelope"]
    binding = snapshot["binding"]
    confirmation = snapshot["confirmation"]
    criteria = envelope["record"]["criteria"]
    if not criteria or not confirmation.get("decided_by"):
        raise WorkflowRunError("needs_configuration", "The accepted specification criteria are unavailable.")
    return {
        "kind": "spec", "source": f"the accepted specification (parent run {binding['parent_run_id']})",
        "work_item_criteria": len(criteria), "criteria": deepcopy(criteria),
        **{key: deepcopy(binding[key]) for key in ("parent_run_id", "version", "hash", "node_id", "entry")},
        "binding": deepcopy(binding), "confirmation": deepcopy(confirmation),
        "accepted_binding": deepcopy(snapshot["accepted_binding"]), "decided_by": confirmation["decided_by"],
        "note": ("each exact accepted-spec criterion ID has a genuine new test or an explicit manual reason; "
                 "whether those tests prove the Given/When/Then stays the person's check; "
                 "the test contract still needs its own human confirmation"),
    }


def criterion_text(criterion: dict[str, Any]) -> str:
    # Never infer semantic coverage.
    return f"Given {criterion['given']}\nWhen {criterion['when']}\nThen {criterion['then']}"
