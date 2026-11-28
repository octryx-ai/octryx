"""Seeding and freshness helpers for Engineering Knowledge Packs."""

from __future__ import annotations

import re
import uuid
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.project.engineering_knowledge import (
    EngineeringKnowledgePack,
    EngineeringKnowledgePackSource,
    EngineeringKnowledgePackVersion,
)
from app.time_utils import utc_now

DEFAULT_MAX_AGE_DAYS = 90

# Deterministic trust-tier inference: exact domain suffix matches only.
_OFFICIAL_DOMAINS = (
    "spring.io",
    "docs.oracle.com",
    "openjdk.org",
    "docs.python.org",
    "kubernetes.io",
    "docs.aws.amazon.com",
    "learn.microsoft.com",
    "docs.docker.com",
    "hibernate.org",
    "jakarta.ee",
    "maven.apache.org",
    "gradle.org",
    "docs.github.com",
)
_VENDOR_DOMAINS = (
    "github.com",
    "atlassian.com",
    "redhat.com",
    "vmware.com",
    "jetbrains.com",
    "hashicorp.com",
    "elastic.co",
    "confluent.io",
)


def infer_trust_tier(url: str) -> str:
    host = (urlparse(str(url or "")).hostname or "").lower()
    if any(host == domain or host.endswith(f".{domain}") for domain in _OFFICIAL_DOMAINS):
        return "official"
    if any(host == domain or host.endswith(f".{domain}") for domain in _VENDOR_DOMAINS):
        return "vendor"
    return "community"


def _source_key_from_url(url: str) -> str:
    parsed = urlparse(str(url or ""))
    seed = f"{parsed.hostname or 'source'}-{parsed.path or ''}".strip("/")
    slug = re.sub(r"[^a-z0-9]+", "-", seed.lower()).strip("-")
    return slug[:180] or "source"


async def seed_pack_sources(
    db: AsyncSession,
    *,
    pack_version: EngineeringKnowledgePackVersion,
    sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_uris = {
        str(uri)
        for uri in (
            await db.execute(
                select(EngineeringKnowledgePackSource.source_uri).where(
                    EngineeringKnowledgePackSource.pack_version_id == pack_version.id
                )
            )
        )
        .scalars()
        .all()
    }
    registered: list[dict[str, Any]] = []
    for entry in sources:
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url") or entry.get("source_uri") or "").strip()
        if not url or url in existing_uris:
            continue
        existing_uris.add(url)
        trust_tier = str(entry.get("trust_tier") or "").strip() or infer_trust_tier(url)
        source = EngineeringKnowledgePackSource(
            id=str(uuid.uuid4()),
            pack_version_id=pack_version.id,
            source_key=_source_key_from_url(url),
            title=str(entry.get("title") or url)[:500],
            source_uri=url[:2000],
            source_type=str(entry.get("source_type") or "research_evidence"),
            trust_tier=trust_tier,
            version_label=str(entry.get("version_label") or "") or None,
        )
        db.add(source)
        registered.append({"source_key": source.source_key, "source_uri": url, "trust_tier": trust_tier})
    await db.flush()
    return registered


async def list_stale_engineering_knowledge_packs(db: AsyncSession) -> list[dict[str, Any]]:
    versions = (
        (
            await db.execute(
                select(EngineeringKnowledgePackVersion)
                .options(selectinload(EngineeringKnowledgePackVersion.pack))
                .where(EngineeringKnowledgePackVersion.status == "published")
            )
        )
        .scalars()
        .all()
    )
    now = utc_now()
    stale: list[dict[str, Any]] = []
    newest_by_pack: dict[str, EngineeringKnowledgePackVersion] = {}
    for version in versions:
        current = newest_by_pack.get(version.pack_id)
        if current is None or int(version.version or 0) > int(current.version or 0):
            newest_by_pack[version.pack_id] = version
    for version in newest_by_pack.values():
        pack: EngineeringKnowledgePack | None = version.pack
        if pack is None or version.published_at is None:
            continue
        policy = dict(pack.freshness_policy or {})
        max_age_days = int(policy.get("max_age_days") or DEFAULT_MAX_AGE_DAYS)
        published_at = version.published_at
        if published_at.tzinfo is None and now.tzinfo is not None:
            published_at = published_at.replace(tzinfo=now.tzinfo)
        age_days = (now - published_at).days
        if age_days > max_age_days:
            stale.append(
                {
                    "pack_id": pack.id,
                    "pack_key": pack.key,
                    "pack_name": pack.name,
                    "stack_key": pack.stack_key,
                    "pack_version_id": version.id,
                    "version": int(version.version or 1),
                    "published_at": version.published_at.isoformat(),
                    "age_days": age_days,
                    "max_age_days": max_age_days,
                    "recommendation": (
                        f"Re-research {pack.name}: knowledge is {age_days} days old "
                        f"(policy allows {max_age_days})."
                    ),
                }
            )
    stale.sort(key=lambda entry: -entry["age_days"])
    return stale


__all__ = [
    "infer_trust_tier",
    "list_stale_engineering_knowledge_packs",
    "seed_pack_sources",
]
