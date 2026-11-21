"""Prompt sections that list a repository's microagents and knowledge entries."""

from __future__ import annotations

from typing import Any


def build_repo_microagents_prompt(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return ""

    parts = ["## Repo Microagents"]
    for entry in entries:
        parts.append(f"### {entry.get('name')}")
        description = str(entry.get("description") or "").strip()
        if description:
            parts.append(description)
        meta_bits: list[str] = []
        source = str(entry.get("repo_label") or entry.get("relative_path") or "").strip()
        if source:
            meta_bits.append(f"source={source}")
        triggers = [str(item).strip() for item in (entry.get("triggers") or []) if str(item).strip()]
        if triggers:
            meta_bits.append("triggers=" + ", ".join(triggers[:6]))
        if meta_bits:
            parts.append("- " + " | ".join(meta_bits))
        parts.append(str(entry.get("instructions") or "").strip())
    return "\n".join(parts)


def build_repo_knowledge_prompt(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return ""

    parts = ["## Repo Knowledge"]
    for entry in entries:
        parts.append(f"### {entry.get('title')}")
        summary = str(entry.get("summary") or "").strip()
        if summary:
            parts.append(summary)
        meta_bits: list[str] = []
        source = str(entry.get("repo_label") or entry.get("relative_path") or "").strip()
        if source:
            meta_bits.append(f"source={source}")
        tags = [str(item).strip() for item in (entry.get("tags") or []) if str(item).strip()]
        if tags:
            meta_bits.append("tags=" + ", ".join(tags[:6]))
        triggers = [str(item).strip() for item in (entry.get("triggers") or []) if str(item).strip()]
        if triggers:
            meta_bits.append("triggers=" + ", ".join(triggers[:6]))
        if meta_bits:
            parts.append("- " + " | ".join(meta_bits))
        parts.append(str(entry.get("excerpt") or "").strip())
    return "\n".join(parts)
