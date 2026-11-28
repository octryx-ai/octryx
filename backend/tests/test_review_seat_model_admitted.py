"""The default review models are always admitted on a seat, derived from review_models.json; a model a
Workspace leaves out is named with the admitted ones before any device is asked."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import Project
from app.services.agent_gateway.engine_keys import ENGINE_CLAUDE_CODE
from app.services.agent_gateway.review_keys import DEFAULT_MODELS
from app.services.agent_gateway.seat_policy import workspace_seat_decision
from app.services.agent_gateway.seat_policy_keys import BASELINE_SEAT_MODELS
from app.services.workflow_runs.review.seat_fallback import _model_not_admitted

SEAT_MODELS = Path(__file__).parents[1] / "app/services/workflow_runs/octryx/seat_models.json"


async def _workspace(db, **policy) -> str:
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:8]}", is_active=True, config={
        "data_policy": {"classification": "internal"},
        "agent_gateway_policy": {"seat_mode": "allowed", **policy}})
    db.add(project)
    await db.commit()
    return project.id


def test_every_default_model_is_in_the_seat_baseline():
    data = json.loads(SEAT_MODELS.read_text(encoding="utf-8"))
    defaults = {DEFAULT_MODELS[ENGINE_CLAUDE_CODE], *data["installation_defaults"].values()}
    assert defaults <= set(BASELINE_SEAT_MODELS)
    assert {"claude-sonnet-5", "claude-opus-5-5"} <= set(BASELINE_SEAT_MODELS)  # what it admitted before stays


@pytest.mark.asyncio
async def test_a_fresh_workspace_without_its_own_seat_models_reviews_on_the_seat_with_the_default(db):
    workspace = await _workspace(db)
    decision = await workspace_seat_decision(db, workspace)
    assert decision.allowed and DEFAULT_MODELS[ENGINE_CLAUDE_CODE] in decision.models
    choice = SimpleNamespace(model=DEFAULT_MODELS[ENGINE_CLAUDE_CODE], engine=ENGINE_CLAUDE_CODE)
    assert await _model_not_admitted(db, SimpleNamespace(project_id=workspace), choice) == ""


@pytest.mark.asyncio
async def test_a_review_model_the_workspace_leaves_out_is_named_with_the_admitted_ones(db):
    workspace = await _workspace(db, seat_models=["claude-opus-5-5"])
    choice = SimpleNamespace(model="claude-sonnet-5-5", engine=ENGINE_CLAUDE_CODE)
    assert await _model_not_admitted(db, SimpleNamespace(project_id=workspace), choice) == (
        "review model claude-sonnet-5-5 is not admitted on the seat; admitted: claude-opus-5-5; next: admit it in "
        "the Workspace seat models")
