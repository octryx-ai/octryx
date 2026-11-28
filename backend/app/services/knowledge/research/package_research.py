"""Research a knowledge package from the web with a governed model. A fixed pipeline (plan, discover, select, draft):
the model decides content, never control flow."""

from __future__ import annotations

import logging
from urllib.parse import urldefrag

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.prompt_catalog.out_of_turn import prompt_set_for

from ....models.project.knowledge_packages import KnowledgePackage, KnowledgePackageDocument
from ...web_search.registry import SourcePolicy, load_policy
from ...web_search.service import governed_search
from ..access.authorization import AuthorizedWorkspace
from ..ledger.errors import InvalidEvidenceRequestError
from ..sources.scope import normalize_products
from ..sources.source_url import normalize_source_url
from .discovery import Candidate, discover, entry_point_hosts, entry_points, verified
from .model import governed_research_model
from .research_steps import (
    MAX_CANDIDATES,
    MAX_TOPIC_CHARS,
    RESULTS_PER_QUERY,
    _append,
    _clean,
    _plan,
    _propose_sources,
    _round,
    _select,
    _versions,
)

logger = logging.getLogger(__name__)


async def _search(
    db: AsyncSession, project_id: str, queries: list[str], *, hosts: list[str], product: str, policy: SourcePolicy
) -> tuple[list[Candidate], list[str]]:
    if not hosts:
        return [], ["skipped:no_trusted_or_entry_point_hosts"]
    candidates: dict[str, Candidate] = {}
    outcomes: list[str] = []
    for query in queries:
        outcome = await governed_search(
            db,
            project_id=project_id,
            query=query,
            num_results=RESULTS_PER_QUERY,
            trusted_only=False,
            product=product,
            restrict_to=hosts,
            policy=policy,
        )
        outcomes.append(f"{outcome.provider or 'none'}:{outcome.reason}")
        for hit in outcome.hits:
            url = urldefrag(hit.url.strip())[0]
            try:
                url = normalize_source_url(url) or ""
            except InvalidEvidenceRequestError:
                continue
            if url.startswith("https://") and url not in candidates and len(candidates) < MAX_CANDIDATES:
                candidates[url] = Candidate(url, _clean(hit.title, 200), _clean(hit.snippet, 300))
    return list(candidates.values()), outcomes


async def _candidates(
    db: AsyncSession, project_id: str, plan: dict, product: str, versions: list[str], *, known_urls: set[str]
) -> tuple[list[Candidate], list[str], dict[str, int], SourcePolicy]:
    policy = await load_policy(db, project_id=project_id)
    pages = await entry_points(plan["seed_urls"], policy)
    hosts = sorted({*policy.trusted_hosts(product), *entry_point_hosts(pages)})
    search, outcomes = (
        await _search(db, project_id, plan["queries"], hosts=hosts, product=product, policy=policy)
        if plan["queries"]
        else ([], [])
    )
    candidates, stats = discover(pages=pages, search=search, product=product, versions=versions, policy=policy)
    stats["trusted_sources"] = len(policy.trusted_patterns(product))
    return [item for item in candidates if item.url not in known_urls], outcomes, stats, policy


async def _grounded(documents: list[dict]) -> list[dict]:
    alive = await verified([document["url"] for document in documents])
    return [document for document in documents if document["url"] in alive]


async def research_package(
    db: AsyncSession,
    *,
    authorized: AuthorizedWorkspace,
    topic: object,
    product: object = None,
    versions: object = None,
    created_by: str | None,
) -> KnowledgePackage:
    text = _clean(topic, MAX_TOPIC_CHARS)
    if len(text) < 3:
        raise InvalidEvidenceRequestError()
    hint_products = normalize_products(product) if product else ()
    hint_versions = [str(v) for v in (versions or []) if str(v).strip()][:8] if isinstance(versions, list) else []
    model = await governed_research_model(db, project_id=authorized.project_id)
    prompts = await prompt_set_for(db, workspace_id=authorized.project_id)
    plan = await _plan(model, text, hint_products[0] if hint_products else None, hint_versions, prompts=prompts)
    try:
        (product_key,) = normalize_products(plan.get("product") or (hint_products[0] if hint_products else ""))
    except (InvalidEvidenceRequestError, ValueError):
        raise InvalidEvidenceRequestError() from None
    package_versions = _versions(plan.get("versions") or hint_versions)
    title = _clean(plan.get("title"), 300) or text[:300]
    candidates, outcomes, stats, policy = await _candidates(
        db, authorized.project_id, plan, product_key, package_versions, known_urls=set()
    )
    documents = await _grounded(
        await _select(
            model,
            title=title,
            product=product_key,
            versions=package_versions,
            candidates=candidates,
            prompts=prompts,
        )
    )
    proposals = await _propose_sources(
        db, authorized.project_id, documents, policy=policy, product=product_key, title=title
    )
    package = KnowledgePackage(
        project_id=authorized.project_id,
        topic=text,
        title=title,
        product=product_key,
        versions=package_versions,
        research={"rounds": [_round(plan, outcomes, len(candidates), model, "", stats, proposals)]},
        created_by=created_by,
    )
    db.add(package)
    await db.flush()
    _append(db, package, documents, start=1)
    await db.commit()
    logger.info(
        "Knowledge package researched: documents=%d candidates=%d workspace=%s",
        len(documents),
        len(candidates),
        authorized.project_id,
    )
    return package


async def extend_package(
    db: AsyncSession,
    *,
    authorized: AuthorizedWorkspace,
    package: KnowledgePackage,
    instruction: object,
) -> int:
    ask = _clean(instruction, MAX_TOPIC_CHARS)
    if len(ask) < 3:
        raise InvalidEvidenceRequestError()
    existing = (
        (await db.execute(select(KnowledgePackageDocument).where(KnowledgePackageDocument.package_id == package.id)))
        .scalars()
        .all()
    )
    known_urls = {item.url for item in existing}
    known = "\n".join(f"- {item.title} ({item.version or 'no version'}) {item.url}" for item in existing[:60])
    model = await governed_research_model(db, project_id=authorized.project_id)
    prompts = await prompt_set_for(db, workspace_id=authorized.project_id)
    plan = await _plan(
        model,
        f"{package.topic}. Extend it: {ask}\nAlready included:\n{known}",
        package.product,
        list(package.versions or []),
        prompts=prompts,
    )
    fresh, outcomes, stats, policy = await _candidates(
        db, authorized.project_id, plan, package.product, list(package.versions or []), known_urls=known_urls
    )
    documents = await _grounded(
        await _select(
            model,
            title=package.title,
            product=package.product,
            versions=list(package.versions or []),
            candidates=fresh,
            instruction=ask,
            known=known,
            prompts=prompts,
        )
    )
    proposals = await _propose_sources(
        db, authorized.project_id, documents, policy=policy, product=package.product, title=package.title
    )
    _append(db, package, documents, start=max((item.ordinal for item in existing), default=0) + 1)
    rounds = list((package.research or {}).get("rounds") or [])
    rounds.append(_round(plan, outcomes, len(fresh), model, ask, stats, proposals))
    package.research = {**(package.research or {}), "rounds": rounds[-20:]}
    added_versions = [v for v in (d["version"] for d in documents) if v and v not in (package.versions or [])]
    if added_versions:
        package.versions = list(package.versions or []) + added_versions
    await db.commit()
    return len(documents)


__all__ = ["extend_package", "research_package"]
