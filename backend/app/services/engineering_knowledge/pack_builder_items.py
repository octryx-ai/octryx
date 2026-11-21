"""Turn archived pack sources into retrievable pack items."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    EngineeringKnowledgePackItem,
    EngineeringKnowledgePackSource,
    EngineeringKnowledgePackVersion,
)
from .archive_store import engineering_archive_exists, read_engineering_archive_text


async def _load_pack_sources(
    db: AsyncSession,
    pack_version: EngineeringKnowledgePackVersion,
) -> Sequence[EngineeringKnowledgePackSource]:
    return (
        await db.execute(
            select(EngineeringKnowledgePackSource)
            .where(EngineeringKnowledgePackSource.pack_version_id == pack_version.id)
            .order_by(EngineeringKnowledgePackSource.source_key.asc())
        )
    ).scalars().all()


def _facts_by_source_key(evidence_ledger: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    facts_by_source_key: dict[str, list[dict[str, Any]]] = {}
    for fact in evidence_ledger:
        facts_by_source_key.setdefault(str(fact.get("source_key") or ""), []).append(fact)
    return facts_by_source_key


async def _create_items_from_archived_sources(
    db: AsyncSession,
    *,
    pack_version: EngineeringKnowledgePackVersion,
    archive_base_path: Path,
    stack_key: str,
    target_versions: dict[str, str],
) -> None:
    sources = await _load_pack_sources(db, pack_version)
    evidence_ledger = list(dict(pack_version.manifest or {}).get("evidence_ledger") or [])
    facts_by_source_key = _facts_by_source_key(evidence_ledger)
    for source in sources:
        if not source.parsed_archive_path:
            continue
        if not engineering_archive_exists(source.parsed_archive_path, archive_base_path=archive_base_path):
            continue
        content = read_engineering_archive_text(source.parsed_archive_path, archive_base_path=archive_base_path).strip()
        if not content:
            continue
        content = _skip_boilerplate(content)
        source_facts = facts_by_source_key.get(source.source_key, [])
        item_content = _build_source_item_content(
            source,
            raw_content=content,
            facts=source_facts,
            target_versions=target_versions,
        )
        db.add(_new_source_item(source, pack_version, item_content, stack_key, target_versions))
    await db.flush()


def _new_source_item(
    source: EngineeringKnowledgePackSource,
    pack_version: EngineeringKnowledgePackVersion,
    item_content: str,
    stack_key: str,
    target_versions: dict[str, str],
) -> EngineeringKnowledgePackItem:
    return EngineeringKnowledgePackItem(
        id=str(uuid.uuid4()),
        pack_version_id=pack_version.id,
        source_id=source.id,
        item_key=f"{source.source_key}-source-evidence",
        title=source.title,
        summary=item_content[:500],
        content=item_content[:12_000],
        tags=[stack_key, source.source_type, source.trust_tier],
        triggers=_source_item_triggers(source, stack_key=stack_key, target_versions=target_versions),
        version_scope={"target_versions": target_versions},
        retrieval_priority="high" if source.trust_tier == "official" else "normal",
        retrieval_rank=10 if source.trust_tier == "official" else 50,
        item_metadata={
            "evidence": [
                {
                    "source_key": source.source_key,
                    "source_id": source.id,
                    "source_uri": source.source_uri,
                    "source_type": source.source_type,
                    "trust_tier": source.trust_tier,
                    "checksum": source.checksum,
                    "evidence_archive_path": source.evidence_archive_path,
                }
            ],
            "evidence_fact_ids": list(dict(source.source_metadata or {}).get("evidence_fact_ids") or []),
            "generated_by": "engineering_pack_research_agent",
        },
    )


def _build_source_item_content(
    source: EngineeringKnowledgePackSource,
    *,
    raw_content: str,
    facts: list[dict[str, Any]],
    target_versions: dict[str, str],
) -> str:
    target_text = ", ".join(f"{coordinate} {version}" for coordinate, version in target_versions.items())
    fact_lines = [
        f"- {fact.get('fact_id')}: {fact.get('claim')}"
        for fact in facts[:12]
        if str(fact.get("fact_id") or "").strip() and str(fact.get("claim") or "").strip()
    ]
    coverage_areas = sorted({str(area) for fact in facts for area in list(fact.get("coverage_areas") or []) if area})
    source_audit = dict(dict(source.source_metadata or {}).get("source_audit") or {})
    guidance_lines = [
        f"Use this archived {source.trust_tier} {source.source_type} source when coding against {target_text}.",
        f"Source: {source.title} ({source.source_uri}).",
        f"Source audit status: {source_audit.get('status') or 'missing'}.",
    ]
    if coverage_areas:
        guidance_lines.append("Covered review areas: " + ", ".join(coverage_areas) + ".")
    guidance_lines.extend(
        [
            "Validate migration or feature guidance against the Evidence Ledger facts below before applying it.",
            "Do not infer unsupported runtime, security, API, or build-tool behavior beyond these archived facts.",
            "",
            "Evidence Ledger facts:",
        ]
    )
    guidance_lines.extend(fact_lines or ["- No source-backed facts were extracted for this source."])
    excerpt = "\n".join(raw_content.splitlines()[:80]).strip()
    if excerpt:
        guidance_lines.extend(["", "Archived source excerpt:", excerpt[:3000]])
    return "\n".join(guidance_lines).strip()


def _source_item_triggers(
    source: EngineeringKnowledgePackSource,
    *,
    stack_key: str,
    target_versions: dict[str, str],
) -> list[str]:
    target_text = " ".join(str(version) for version in target_versions.values() if str(version).strip())
    base = [stack_key, source.source_type, source.title, source.source_key]
    if target_text:
        base.append(target_text)
    return [item for item in dict.fromkeys(" ".join(base).lower().replace("-", " ").split()) if len(item) > 2][:12]


def _skip_boilerplate(text: str) -> str:
    """Skip leading navigation/cookie/login boilerplate in scraped docs.

    Scans lines from the top and returns the text starting from the first
    line that looks like real content (a heading, a sentence, or a list
    item that is not a bare hyperlink or a single short word).
    """
    _nav_patterns = re.compile(
        r"^\s*(-\s*)?\[?(skip to|accessibility|sign.?in|sign.?out|create an account"
        r"|country|oracle account|help|cookie|privacy policy|terms of use"
        r"|copyright|all rights reserved)\]?",
        re.IGNORECASE,
    )
    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if _nav_patterns.match(stripped):
            continue
        # bare markdown link with no surrounding text, e.g. "[](https://...)"
        if re.match(r"^\[.*?\]\(https?://[^)]+\)\s*$", stripped):
            continue
        # very short line (single word or icon) that is typical nav
        if len(stripped) < 8 and not stripped.startswith("#"):
            continue
        # found first real content line
        return "\n".join(lines[i:])
    return text
