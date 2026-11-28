"""Whether hybrid search in one Workspace is reranked, and the closed reason when it is held. The same checks as the
search path, without a model call."""

from __future__ import annotations

import os
from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from ..embedding.bedrock import bedrock_runtime_hold
from ..embedding.port import EmbeddingError, EmbeddingState
from ..embedding.selection import REMOTE_KIND_RERANKER, admit_remote
from .catalog import reranker_spec
from .selection import RERANKER_ENV, reranker_region

STATE_OK = "ok"


def reranker_runtime_precondition(environ: Mapping[str, str] | None = None) -> dict[str, str | None]:
    # The classification settings use this too, so they never admit a reranker the search runtime holds.
    source = os.environ if environ is None else environ
    key = str(source.get(RERANKER_ENV) or "").strip()
    if not key:
        return {"state": EmbeddingState.NEEDS_CONFIGURATION.value, "hold_reason": "reranker_not_configured",
                "data_policy_class": None}
    try:
        spec = reranker_spec(key)
    except KeyError:
        return {"state": EmbeddingState.NEEDS_CONFIGURATION.value, "hold_reason": "reranker_unknown",
                "data_policy_class": None}
    hold = bedrock_runtime_hold(reranker_region(source))
    if hold is not None:
        return {"state": EmbeddingState.NEEDS_CONFIGURATION.value, "hold_reason": hold,
                "data_policy_class": spec.data_policy_class}
    return {"state": STATE_OK, "hold_reason": None, "data_policy_class": spec.data_policy_class}


async def reranker_admission(
    db: AsyncSession, *, project_id: str, environ: Mapping[str, str] | None = None
) -> dict[str, str | None]:
    precondition = reranker_runtime_precondition(environ)
    if precondition["state"] != STATE_OK:
        return precondition
    data_policy_class = precondition["data_policy_class"]
    try:
        await admit_remote(
            db, project_id=project_id, data_policy_class=data_policy_class, model_kind=REMOTE_KIND_RERANKER
        )
    except EmbeddingError as error:
        return {"state": error.state.value, "hold_reason": error.reason, "data_policy_class": data_policy_class}
    return precondition


__all__ = ["STATE_OK", "reranker_admission", "reranker_runtime_precondition"]
