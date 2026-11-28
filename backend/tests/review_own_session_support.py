"""Shared helpers for the test_review_own_session_* modules."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.models import Project
from app.services.agent_gateway.review_keys import DEFAULT_MODELS
from tests.test_workflow_run_pause import _turn
from tests.workflow_run_review_support import PASS, _started

HAIKU, TERRA = "claude-haiku-5-5", "gpt-6.1-terra"  # Terra: the Codex platform default


DEFAULT = DEFAULT_MODELS["claude_code"]  # the Claude Code platform default (review_models.json: Sonnet)


def _runtime(model: str, **extra) -> dict:
    return {"model": model, "provider_name": "test", "driver": "litellm", "use_case_tags": ["coding"], **extra}


@pytest.fixture
def workspace_runtimes(monkeypatch):
    import app.agent.providers as providers
    import app.services.workflow_routing.proposal_model as proposal_model
    import app.services.workflow_runs.review.model as review_model

    state = SimpleNamespace(runtimes=[_runtime("qwen3.5-9b"), _runtime(DEFAULT)], called=[], answer=PASS)

    async def runtimes(db, project_id):
        return list(state.runtimes)

    async def admit(db, runtimes, **kwargs):
        return SimpleNamespace(allowed=True, reason=None, state="allowed",
                               dispatchable_runtimes=lambda: list(runtimes))

    class Client:
        def __init__(self, **runtime):
            self.runtime = runtime

        async def chat(self, *, messages, model, **kwargs):
            import json

            state.called.append((model, messages))
            return {"content": json.dumps(state.answer), "usage": {"prompt_tokens": 120, "completion_tokens": 30}}

    monkeypatch.setattr(proposal_model, "_workspace_runtimes", runtimes)
    monkeypatch.setattr(review_model, "admit_runtimes_for_dispatch", admit)
    monkeypatch.setattr(providers, "get_provider", lambda **runtime: Client(**runtime))
    return state


async def _awaiting_review(db, tmp_path, *, workspace_policy: dict | None = None, target: dict | None = None):
    run, session = await _started(db, tmp_path)
    await _turn(db, session.id, ["knowledge_search"])
    assert (run.status, run.waiting_kind) == ("waiting", "awaiting_review")
    project = Project(id=str(uuid.uuid4()), name=f"review-{uuid.uuid4().hex[:6]}", is_active=True,
                      config={"agent_gateway_policy": workspace_policy} if workspace_policy else {})
    db.add(project)
    await db.flush()
    run.project_id = project.id
    if target is not None:
        run.context = {**dict(run.context or {}), "runtime_target": target}
    await db.commit()
    return run, session


def _codex_policy(review: dict | None = None) -> dict:
    return {"engines": {"allowed": ["claude_code", "codex"], "default": "codex"},
            **({"review": review} if review else {})}
