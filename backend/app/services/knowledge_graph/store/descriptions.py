"""Description accumulation, compaction and embedding for graph nodes and edges."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.prompt_catalog.out_of_turn import prompt_set_for

from ....models import KnowledgeGraphNode
from ....time_utils import utc_now
from ...knowledge_embedding import EmbeddingConfigurationError, resolve_knowledge_embedding_runtime

# The package name keeps the log records under the store's logger.
logger = logging.getLogger(__package__)

_DESCRIPTION_SEPARATOR = "\n"
_MAX_DESCRIPTION_CHARS = 2400


def merge_descriptions(existing: str, incoming: str) -> str:
    """LightRAG-style description accumulation: an entity seen in several sources
    keeps ALL distinct description fragments instead of last-write-wins. The
    merged text is capped; ``resummarize_node_description`` compacts it with the
    governed summarize runtime when it overflows."""
    existing = str(existing or "").strip()
    incoming = str(incoming or "").strip()
    if not incoming:
        return existing
    if not existing:
        return incoming[:_MAX_DESCRIPTION_CHARS]
    fragments = [fragment.strip() for fragment in existing.split(_DESCRIPTION_SEPARATOR) if fragment.strip()]
    normalized = {fragment.lower() for fragment in fragments}
    if incoming.lower() in normalized or any(incoming.lower() in fragment.lower() for fragment in fragments):
        return existing
    merged = _DESCRIPTION_SEPARATOR.join([*fragments, incoming])
    return merged[:_MAX_DESCRIPTION_CHARS]


async def _embed_text_for(db: AsyncSession, text: str) -> dict[str, Any] | None:
    if not text.strip():
        return None
    try:
        provider = await resolve_knowledge_embedding_runtime(db)
        return {
            "embedding": provider.embed_text(text),
            "embedding_provider": provider.provider_id,
            "embedding_model": provider.model,
            "embedding_version": provider.version,
            "embedding_updated_at": utc_now(),
        }
    except EmbeddingConfigurationError as exc:
        logger.warning("Graph embedding unavailable: %s", exc)
        return None


async def resummarize_node_description(db: AsyncSession, *, node_id: str, generate) -> bool:
    """Compact an overflowing accumulated description via the governed summarize
    runtime. Returns True when the description was rewritten."""
    node = await db.get(KnowledgeGraphNode, node_id)
    if node is None or len(node.description or "") < _MAX_DESCRIPTION_CHARS:
        return False
    prompt = (await prompt_set_for(db, workspace_id=node.project_id)).render(
        "knowledge.graph.resummarize", display_name=node.display_name, description=node.description
    )
    summary = str(await generate(prompt) or "").strip()
    if not summary:
        return False
    node.description = summary[:_MAX_DESCRIPTION_CHARS]
    vector = await _embed_text_for(db, f"{node.display_name}. {node.description}")
    if vector is not None:
        for key, value in vector.items():
            setattr(node, key, value)
    await db.flush()
    return True
