"""``usage_events.dispatch_owner``: the governed call's owner is a column.

The column is written by
every governed platform call that records a ``UsageEvent`` with a registered owner; the proposal's
own write is asserted in ``test_workflow_proposal.py``. ``request_id`` keeps its value.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

import app.agent.core.execution_support as execution_support_module
from app.models import UsageEvent, User
from app.services.budget import UsageCostAttribution
from tests.alembic_model_parity_support import (
    DIALECTS,
    migrated_database,
    missing_model_objects,
    schema_drift,
)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_the_migrated_head_has_no_drift_from_the_model(dialect, tmp_path: Path):
    with migrated_database(dialect, tmp_path) as database:
        assert missing_model_objects(database.run(schema_drift)) == []


@pytest.mark.asyncio
async def test_governed_usage_writers_record_their_registered_owner(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    async def fixed_attribution(*args, **kwargs):
        return UsageCostAttribution(
            provider="fake", model="m", tokens_in=0, tokens_out=0, effective_tokens_in=0,
            cost=Decimal("0"), status="test_fixed_cost",
        )

    monkeypatch.setattr(execution_support_module, "compute_usage_event_cost_attribution", fixed_attribution)
    session_id = str(uuid.uuid4())
    common = {"db": db, "session_id": session_id, "user_id": admin.id, "provider": "fake"}
    usage = {"prompt_tokens": 3, "completion_tokens": 2}

    # The main chat turn (engine runtime chain), a work item analysis, and a call without an owner.
    await execution_support_module.record_engine_turn_usage_event(**common, model="turn", usage=usage, request_id="r1")
    await execution_support_module.record_usage_event(
        **common, model="node", usage=usage, dispatch_owner="work_item_analysis"
    )
    await execution_support_module.record_usage_event(**common, model="plain", usage=usage)
    with pytest.raises(ValueError, match="Unregistered provider-dispatch owner"):
        await execution_support_module.record_usage_event(**common, model="bad", usage=usage, dispatch_owner="nobody")

    rows = (await db.execute(select(UsageEvent).where(UsageEvent.session_id == session_id))).scalars().all()
    owners = {row.model: (row.dispatch_owner, row.request_id) for row in rows}
    assert owners["turn"] == ("engine_runtime_chain", "r1")
    assert owners["node"][0] == "work_item_analysis"
    assert owners["plain"][0] is None
    assert "bad" not in owners
