"""Evidence and evaluation artifacts a pack build attaches to the version manifest."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import EngineeringKnowledgePackItem, EngineeringKnowledgePackVersion
from .evidence_ledger import build_coverage_matrix, build_evidence_ledger
from .pack_builder_items import _facts_by_source_key, _load_pack_sources
from .pack_evaluation import evaluate_pack_for_coding_agent, run_adversarial_pack_review


async def _build_and_attach_evidence_artifacts(
    db: AsyncSession,
    *,
    pack_version: EngineeringKnowledgePackVersion,
    archive_base_path: Path,
    stack_key: str,
    target_versions: dict[str, str],
) -> list[dict[str, Any]]:
    sources = await _load_pack_sources(db, pack_version)
    evidence_ledger = build_evidence_ledger(
        sources=list(sources),
        archive_base_path=archive_base_path,
        stack_key=stack_key,
        target_versions=target_versions,
    )
    coverage_matrix = build_coverage_matrix(evidence_ledger=evidence_ledger, stack_key=stack_key)
    manifest_metadata = dict(pack_version.manifest or {})
    manifest_metadata["evidence_ledger"] = evidence_ledger
    manifest_metadata["coverage_matrix"] = coverage_matrix
    pack_version.manifest = manifest_metadata

    facts_by_source_key = _facts_by_source_key(evidence_ledger)
    for source in sources:
        source_metadata = dict(source.source_metadata or {})
        source_metadata["evidence_fact_ids"] = [
            str(fact.get("fact_id") or "") for fact in facts_by_source_key.get(source.source_key, [])
        ]
        source.source_metadata = source_metadata
    return evidence_ledger


async def _build_and_attach_evaluation_artifacts(
    db: AsyncSession,
    *,
    pack_version: EngineeringKnowledgePackVersion,
) -> None:
    items = (
        await db.execute(
            select(EngineeringKnowledgePackItem)
            .where(EngineeringKnowledgePackItem.pack_version_id == pack_version.id)
            .order_by(EngineeringKnowledgePackItem.retrieval_rank.asc(), EngineeringKnowledgePackItem.item_key.asc())
        )
    ).scalars().all()
    manifest_metadata = dict(pack_version.manifest or {})
    evidence_ledger = list(manifest_metadata.get("evidence_ledger") or [])
    coverage_matrix = dict(manifest_metadata.get("coverage_matrix") or {})
    manifest_metadata["coding_agent_evaluation"] = evaluate_pack_for_coding_agent(
        items=list(items),
        evidence_ledger=evidence_ledger,
        coverage_matrix=coverage_matrix,
    )
    manifest_metadata["adversarial_review"] = run_adversarial_pack_review(
        items=list(items),
        evidence_ledger=evidence_ledger,
        coverage_matrix=coverage_matrix,
    )
    pack_version.manifest = manifest_metadata
