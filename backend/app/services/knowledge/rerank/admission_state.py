"""Whether hybrid search in one Workspace is reranked, and the closed reason when it is held.

The same two checks the search path makes (``retrieval/hybrid._reranked``), without a model call:

1. the Instance reranker (``OCTRYX_KNOWLEDGE_RERANKER``, read as a catalog key only, no client
   is built): absent is ``needs_configuration`` / ``reranker_not_configured``, an unknown key
   ``needs_configuration`` / ``reranker_unknown``;
2. whether the runtime can build the reranker's client at all (``embedding/bedrock.bedrock_runtime_hold``,
   the same check the search runtime uses): ``needs_configuration`` / ``region_missing`` or
   ``runtime_missing``, so the settings never say ``ok`` where search reports ``rerank: needs_configuration``;
3. the Workspace's admission through the data-policy gate (``embedding/selection.admit_remote``): an
   unresolved classification is ``needs_configuration`` with the gate's code
   (``workspace_data_classification_missing`` or ``workspace_data_classification_unknown``), a
   classification above the reranker's allowance is ``denied`` / ``data_policy_class_insufficient``.

Otherwise the state is ``ok`` and the hold reason is ``None``.
"""

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
    """Checks 1 and 2 without a Workspace: ``{state, hold_reason, data_policy_class}``.

    ``state`` is ``ok`` (with the reranker's ``data_policy_class``) or ``needs_configuration`` with the hold
    reason. The classification settings (``data_policy/effects``) use this too, so they never admit a reranker
    the search runtime holds.
    """
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
    """``{state, hold_reason, data_policy_class}`` of the Instance reranker for one Workspace."""
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
