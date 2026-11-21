"""Hybrid knowledge retrieval: the single entry point over chunks + graph."""

from .service import (
    MODE_LOCAL,
    MODE_MIX,
    MODE_NAIVE,
    build_context_block,
    retrieve_knowledge,
)

__all__ = [
    "MODE_LOCAL",
    "MODE_MIX",
    "MODE_NAIVE",
    "build_context_block",
    "retrieve_knowledge",
]
