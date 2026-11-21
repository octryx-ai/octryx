"""A search measures its stages, so a slow search can be explained (``stage_timing.py``)."""

from __future__ import annotations

import asyncio

from app.services.knowledge.retrieval.stage_timing import measuring, timed_stage


async def test_stages_are_collected_by_every_open_measurement_and_nest() -> None:
    with measuring() as outer:
        with measuring() as workspace:
            with timed_stage("vector"):
                with timed_stage("embed"):
                    await asyncio.sleep(0.01)
            with timed_stage("lexical"):
                await asyncio.sleep(0)
        with timed_stage("origin"):
            await asyncio.sleep(0)
    inner = workspace.as_dict()
    total = outer.as_dict()
    assert set(inner) == {"vector", "embed", "lexical", "total"}
    assert inner["vector"] >= inner["embed"] >= 9, "embed lies inside vector"
    assert "origin" in total and "origin" not in inner, "a stage after the inner block counts only outside"
    assert total["total"] >= inner["total"]


def test_a_stage_outside_any_measurement_costs_nothing_and_records_nothing() -> None:
    with timed_stage("lexical"):
        pass
    with measuring() as timer:
        pass
    assert timer.as_dict() == {"total": timer.as_dict()["total"]}
