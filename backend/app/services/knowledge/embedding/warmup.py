"""Loads the local query embedder once at startup, in the background.

The local embedder verifies its model artifact and loads the model on first use. On nonprod the first search
of a process paid that (``embed`` 9 s of a 15 s search). A background task started by the application lifespan
does it right after start, so no search waits for it. Only a local space is warmed: a remote space would spend a
provider call on nothing. Failures leave the embedder as it was (the next search loads it again) and are logged
with a fixed state only.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable

from .catalog import EmbeddingProvider
from .port import EmbeddingError, EmbeddingPurpose, EmbeddingRuntime
from .selection import SPACE_ENV

logger = logging.getLogger(__name__)

WARMUP_TEXT = "warm up"


async def warm_embedder(embedding: EmbeddingRuntime | None) -> bool:
    """Load and exercise a local embedder once; ``True`` when it answered. Never raises."""
    if embedding is None or embedding.space.provider is not EmbeddingProvider.LOCAL:
        return False
    try:
        await embedding.embedder.embed([WARMUP_TEXT], EmbeddingPurpose.QUERY)
    except EmbeddingError as error:
        logger.warning("Local embedder warm-up failed: space=%s state=%s", embedding.space.key, error.state.value)
        return False
    except Exception:  # noqa: BLE001 - a warm-up must never take the application down
        logger.warning("Local embedder warm-up failed: space=%s state=unexpected", embedding.space.key)
        return False
    logger.info("Local embedder warmed up: space=%s", embedding.space.key)
    return True


def _configured_embedding() -> EmbeddingRuntime | None:
    from ..runtime import get_evidence_runtime

    # Without a configured space there is nothing to warm, and the runtime is left to the first request.
    if not os.environ.get(SPACE_ENV, "").strip():
        return None
    try:
        return get_evidence_runtime().embedding
    except Exception:  # noqa: BLE001 - an unconfigured runtime answers needs_configuration per request
        return None


_TASK: asyncio.Task[bool] | None = None


def start_embedder_warmup(
    embedding: Callable[[], EmbeddingRuntime | None] = _configured_embedding,
) -> asyncio.Task[bool]:
    """Schedule the warm-up on the running loop and return its task; the lifespan does not wait for it."""
    global _TASK

    async def run() -> bool:
        # On the loop, not in a thread: the process-wide runtime is built once, and the warmed embedder must be
        # the one searches use.
        return await warm_embedder(embedding())

    _TASK = asyncio.get_running_loop().create_task(run(), name="knowledge-embedder-warmup")
    return _TASK


__all__ = ["WARMUP_TEXT", "start_embedder_warmup", "warm_embedder"]
