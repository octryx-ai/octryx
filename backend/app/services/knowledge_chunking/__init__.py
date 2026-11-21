"""Knowledge chunking: the naive vector-RAG chunk layer (tier 1)."""

from .chunker import TextChunk, chunk_document, estimate_tokens
from .service import (
    index_source_chunks,
    reindex_knowledge_chunks,
    search_knowledge_chunks,
)

__all__ = [
    "TextChunk",
    "chunk_document",
    "estimate_tokens",
    "index_source_chunks",
    "reindex_knowledge_chunks",
    "search_knowledge_chunks",
]
