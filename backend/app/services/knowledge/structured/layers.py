"""The layers a structured build knows: what each selects, extracts and links.

A layer is three steps over a :class:`BuildContext`:

- ``select``: the current revisions it reads (profile selectors, never title guessing);
- ``extract``: one revision to an :class:`~.facts.Extraction` (rule-based, no model call);
- ``link``: the cross-source edges it owns once every layer is extracted (may be ``None``); it is
  given the slice ``deadline`` and its own previous ``partial`` result to resume
  (``build_linkage.py``).

The build runs layers in :data:`~.profile.LAYERS` order and links after all of them, so the
configuration layer can link to the manual layer's parameters.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..identity.workspace import WorkspaceId
from ..runtime import EvidenceRuntime
from .facts import Extraction
from .manual import EXTRACTOR as MANUAL_EXTRACTOR
from .manual import extract_manual
from .profile_types import LAYER_CONFIGURATION, LAYER_MANUAL, LAYER_OPERATIONS, StructuredProfile
from .sources import Candidate, current_revisions, load_span_inputs


@dataclass
class BuildContext:
    db: AsyncSession
    runtime: EvidenceRuntime | None
    workspace: WorkspaceId
    project_id: str
    profile: StructuredProfile
    # Per-build memo shared by the layers (connector scopes, parsed indexes).
    memo: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LayerSpec:
    name: str
    select: Callable[[BuildContext], Awaitable[list[Candidate]]]
    extract: Callable[[BuildContext, Candidate], Awaitable[tuple[str, Extraction]]]
    link: Callable[..., Awaitable[dict[str, Any]]] | None = None


async def _select_manuals(context: BuildContext) -> list[Candidate]:
    return await current_revisions(context.db, context.project_id, media_types=context.profile.manual_media_types)


async def _extract_manual(context: BuildContext, candidate: Candidate) -> tuple[str, Extraction]:
    spans = await load_span_inputs(context.db, context.project_id, candidate.revision_id)
    extraction = extract_manual(spans, context.profile, document_key=candidate.source_key, title=candidate.title)
    return MANUAL_EXTRACTOR, extraction


async def _link_manuals(context: BuildContext, *, deadline: float, progress: dict | None) -> dict[str, Any]:
    from .similarity import link_similar_sections

    return await link_similar_sections(context, deadline=deadline, progress=progress)


async def _link_configuration(context: BuildContext, *, deadline: float, progress: dict | None) -> dict[str, Any]:
    # One bounded in-memory computation over the Workspace's settings; it does not resume.
    from .config_linkage import link_configuration

    return await link_configuration(context)


def layer_specs() -> dict[str, LayerSpec]:
    from .config_layer import extract_config_file, select_config_files
    from .ops_layer import extract_operations, select_operations

    return {
        LAYER_MANUAL: LayerSpec(LAYER_MANUAL, _select_manuals, _extract_manual, _link_manuals),
        LAYER_CONFIGURATION: LayerSpec(
            LAYER_CONFIGURATION, select_config_files, extract_config_file, _link_configuration
        ),
        LAYER_OPERATIONS: LayerSpec(LAYER_OPERATIONS, select_operations, extract_operations),
    }


__all__ = ["BuildContext", "LayerSpec", "layer_specs"]
