"""The bot's facts on a run (``context.pr_review``) and the pull request its posts go to."""

from __future__ import annotations

from typing import Any

from ...models import WorkflowRun
from ..workflow_runs.platform.repo_ref import parse_repository
from .providers import POST_TOOLS, pr_key
from .starter import CONTEXT_KEY


def facts_of(run: WorkflowRun) -> dict[str, Any]:
    return dict(dict(run.context or {}).get(CONTEXT_KEY) or {})


def set_facts(run: WorkflowRun, **values: Any) -> None:
    run.context = {**dict(run.context or {}), CONTEXT_KEY: {**facts_of(run), **values}}


def post_target(run: WorkflowRun) -> tuple[str, dict[str, Any]] | None:
    ref = parse_repository(run.repository)
    facts = facts_of(run)
    if ref is None or ref.provider not in POST_TOOLS or not facts.get("pr_id"):
        return None
    return ref.provider, {**ref.args(), pr_key(ref.provider): str(facts["pr_id"])}
