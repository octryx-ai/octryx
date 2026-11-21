"""Prompt composition policy helpers for agent run preparation."""

from __future__ import annotations


def compose_memory_prompt(*, engineering_knowledge_prompt: str = "") -> str:
    """The injected knowledge fragment of a turn: only the engineering-pack runtime resolution.

    Session memory is not injected: it is the Knowledge Memory lobe, recalled explicitly through
    ``memory_recall``. Nor is project knowledge: governed Knowledge is recalled through
    ``knowledge_search``.
    """

    return engineering_knowledge_prompt or ""
