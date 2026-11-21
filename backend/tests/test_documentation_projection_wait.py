"""The published-version sync waits, bounded, for the asynchronous index projection (live S3.2 follow-up).

Live: the sync of the new page completed, but the binding ran before the projector committed the head and the step
failed with ``index_timeout``; a retry 11 seconds later passed. The step now polls only while the refusal is
``head_not_projected``; any other refusal ends the wait at once and the authoritative binding reports it.
"""
from __future__ import annotations

import pytest

from app.services.workflow_runs.documentation.knowledge import await_projection
from app.services.workflow_runs.documentation.knowledge_proof import (
    BINDING_DIGEST,
    BINDING_HEAD,
    BindingRefusedError,
)


def _probe(outcomes):
    calls = []

    async def probe():
        calls.append(1)
        outcome = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
        if outcome is not None:
            raise BindingRefusedError(outcome, "refused")

    return probe, calls


async def _no_sleep(_seconds):
    return None


@pytest.mark.asyncio
async def test_it_binds_once_the_projector_has_committed():
    probe, calls = _probe([BINDING_HEAD, BINDING_HEAD, None])
    assert await await_projection(probe, sleep=_no_sleep) is True
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_another_refusal_ends_the_wait_at_once():
    probe, calls = _probe([BINDING_HEAD, BINDING_DIGEST, None])
    assert await await_projection(probe, sleep=_no_sleep) is False
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_the_wait_is_bounded():
    probe, calls = _probe([BINDING_HEAD])
    assert await await_projection(probe, timeout=0, sleep=_no_sleep) is False
    assert len(calls) == 1
