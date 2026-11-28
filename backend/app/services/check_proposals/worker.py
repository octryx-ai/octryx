"""Drafting the proposals that have no draft yet, with the review model of their newest occurrence's run."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import CheckProposal, WorkflowRun

logger = logging.getLogger(__name__)
MAX_PER_PASS = 5


def stack_of(signature: dict[str, Any]) -> str:
    from ..engineering_knowledge.stacks import built_in

    paths = [str(path) for item in signature.get("occurrences") or [] if isinstance(item, dict)
             for path in item.get("paths") or []] + [str(signature.get("file_pattern") or "")]
    for name, stack in dict(built_in().get("stacks") or {}).items():
        suffixes = tuple(str(item).lower() for item in stack.get("code_suffixes") or [])
        if suffixes and any(path.lower().endswith(suffixes) for path in paths):
            return str(name)
    return ""


async def _model_for(db: AsyncSession, run: WorkflowRun, model_factory: Any) -> Any:
    from ..workflow_runs.review.call_inputs import _review_model
    from ..workflow_runs.review.choice import review_choice
    from ..workflow_runs.review.model import governed_review_model
    from ..workflow_runs.review.reviewer_agent import reviewer_setup

    setup = await reviewer_setup(db, run)
    choice = await review_choice(db, run, {}) if not isinstance(setup, str) else setup
    if isinstance(setup, str) or isinstance(choice, str):
        return f"no model to draft the check: {setup if isinstance(setup, str) else choice}"
    return await _review_model(model_factory or governed_review_model, db, run, setup, choice)


async def draft_due(db: AsyncSession, *, model_factory: Any = None,
                    signature_of: Any = None) -> int:
    from .draft import draft_proposal

    if signature_of is None:
        import importlib
        import importlib.util

        if importlib.util.find_spec("app.services.workflow_runs.corrections") is None:
            return 0  # the signature store is not installed yet
        signature_of = importlib.import_module("app.services.workflow_runs.corrections").get_signature
    due = list((await db.execute(select(CheckProposal).where(CheckProposal.state == "proposed")
                                 .order_by(CheckProposal.created_at).limit(50))).scalars())
    done = 0
    for proposal in [item for item in due if not dict(item.draft or {}).get("rule")
                     and not dict(item.draft or {}).get("problem")][:MAX_PER_PASS]:
        signature = await signature_of(db, proposal.signature_id)
        runs = [str(item.get("run_id")) for item in dict(proposal.evidence or {}).get("occurrences") or []
                if isinstance(item, dict) and item.get("run_id")]
        run = await db.get(WorkflowRun, runs[0]) if runs else None
        stack = stack_of(signature or {})
        model = await _model_for(db, run, model_factory) if run is not None and stack else None
        if signature is None or run is None or not stack or isinstance(model, str) or model is None:
            why = model if isinstance(model, str) else "no signature, run or stack to draft from"
            proposal.draft = {**dict(proposal.draft or {}), "problem": why}
        else:
            try:
                done += int(await draft_proposal(db, proposal, signature, stack, model))
            except Exception:  # noqa: BLE001 - logged; the proposal says it and the next ones still draft
                logger.exception("check_proposals.draft_failed proposal=%s", proposal.id)
                proposal.draft = {**dict(proposal.draft or {}), "problem": "the drafting model failed"}
        await db.commit()
    return done


__all__ = ["draft_due", "stack_of"]
