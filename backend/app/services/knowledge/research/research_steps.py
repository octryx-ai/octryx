"""The model-facing steps of package research: plan, select, and the records they leave."""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.prompt_catalog import PromptSet

from ....models.project.knowledge_packages import KnowledgePackage, KnowledgePackageDocument
from ...web_search.patterns import suggested_pattern
from ...web_search.registry import URL_TRUSTED, SourcePolicy, propose_sources
from ..ledger.errors import InvalidEvidenceRequestError
from ..sources.scope import normalize_version
from .discovery import Candidate
from .model import ResearchModel

MAX_TOPIC_CHARS = 500
MAX_QUERIES = 6
RESULTS_PER_QUERY = 8
MAX_CANDIDATES = 40
MAX_DOCUMENTS = 25
ROLES = ("migration_guide", "release_notes", "configuration_changelog", "reference", "specification")

# The JSON answers the planner and the selection parse: fixed protocol strings, they fill
# ``{answer_contract}`` of ``knowledge.package.plan_system`` / ``knowledge.package.select_system``.
PLAN_ANSWER_CONTRACT = (
    "Answer only with a JSON object: "
    '{"title": str, "product": str (lower-case key such as spring-boot or shipping-protocol), "versions": [str], '
    f'"queries": [str] (at most {MAX_QUERIES}, aimed at the vendor\'s own pages), '
    '"seed_urls": [str] (at most 10 official entry-point URLs you know: the documentation index, the project '
    "wiki home, the release notes overview, the migration guide page)}."
)
SELECT_ANSWER_CONTRACT = (
    "Answer only with a JSON object: "
    '{"documents": [{"result": int, "version": str|null, "role": str, "title": str, "rationale": str}]} '
    f"with at most {MAX_DOCUMENTS} documents."
)


def _clean(text: object, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


async def _plan(
    model: ResearchModel, topic: str, product: str | None, versions: list[str], *, prompts: PromptSet
) -> dict:
    hints = f"\nProduct hint: {product}" if product else ""
    hints += f"\nVersion hints: {', '.join(versions)}" if versions else ""
    system = prompts.render("knowledge.package.plan_system", answer_contract=PLAN_ANSWER_CONTRACT)
    plan = await model.json(system=system, user=f"Topic: {topic}{hints}")
    queries = [_clean(query, 200) for query in plan.get("queries") or [] if _clean(query, 200)][:MAX_QUERIES]
    seeds = [str(url).strip() for url in plan.get("seed_urls") or [] if str(url).strip()][:10]
    if not queries and not seeds:
        raise InvalidEvidenceRequestError()
    return {**plan, "queries": queries, "seed_urls": seeds}


def _versions(raw: object) -> list[str]:
    versions: list[str] = []
    for value in raw if isinstance(raw, list) else []:
        try:
            version = normalize_version(str(value))
        except InvalidEvidenceRequestError:
            continue
        if version and version not in versions:
            versions.append(version)
    return versions[:8]


_PRE_RELEASE = re.compile(r"[-.]?(m\d+|rc\d*|snapshot|alpha\d*|beta\d*)$", re.I)


def is_pre_release(version: str | None) -> bool:
    return bool(version and _PRE_RELEASE.search(version))


def _documents(selection: dict, candidates: list[Candidate], versions: list[str]) -> list[dict]:
    allow_pre_release = any(is_pre_release(version) for version in versions)
    chosen: list[dict] = []
    seen: set[int] = set()
    for item in (selection.get("documents") or [])[:MAX_DOCUMENTS]:
        if not isinstance(item, dict) or type(item.get("result")) is not int:
            continue
        index = item["result"]
        if not 1 <= index <= len(candidates) or index in seen or item.get("role") not in ROLES:
            continue
        seen.add(index)
        try:
            version = normalize_version(item.get("version")) if item.get("version") else None
        except InvalidEvidenceRequestError:
            version = None
        if is_pre_release(version) and not allow_pre_release:
            continue
        candidate = candidates[index - 1]
        chosen.append(
            {
                "url": candidate.url,
                "title": _clean(item.get("title"), 300) or candidate.title or candidate.url,
                "version": version,
                "role": item["role"],
                "rationale": _clean(item.get("rationale"), 500),
            }
        )
    return chosen


async def _select(
    model: ResearchModel,
    *,
    title: str,
    product: str,
    versions: list[str],
    candidates: list[Candidate],
    instruction: str = "",
    known: str = "",
    prompts: PromptSet,
) -> list[dict]:
    if not candidates:
        return []
    listing = "\n".join(f"{i}. {c.title} — {c.url}\n   {c.snippet}" for i, c in enumerate(candidates, start=1))
    extra = f"\nThe author asks: {instruction}" if instruction else ""
    extra += f"\nAlready in the package (do not choose again):\n{known}" if known else ""
    selection = await model.json(
        system=prompts.render(
            "knowledge.package.select_system", roles=", ".join(ROLES), answer_contract=SELECT_ANSWER_CONTRACT
        ),
        user=f"Package: {title}\nProduct: {product}\nVersions: {', '.join(versions)}{extra}\n\nResults:\n{listing}",
        max_tokens=6000,
    )
    return _documents(selection, candidates, versions)


async def _propose_sources(
    db: AsyncSession, project_id: str, documents: list[dict], *, policy: SourcePolicy, product: str, title: str
) -> list[str]:
    pending: dict[str, tuple[str, str, str, str | None]] = {}
    for document in documents:
        if policy.state_of(document["url"], product) == URL_TRUSTED:
            continue
        pattern = suggested_pattern(document["url"])
        if pattern and pattern not in pending:
            reason = f"Research for {title!r} chose {document['title']!r} from this source."
            pending[pattern] = (pattern, document["url"], reason, product)
    return await propose_sources(db, project_id=project_id, proposals=list(pending.values()))


def _round(
    plan: dict,
    outcomes: list[str],
    candidates: int,
    model: ResearchModel,
    instruction: str,
    stats: dict,
    proposals: list[str],
) -> dict:
    return {
        "instruction": instruction,
        "queries": plan["queries"],
        "seed_urls": plan["seed_urls"],
        "discovery": stats,
        "search_outcomes": outcomes,
        "source_proposals": proposals,
        "candidates": candidates,
        "model_usage": model.usage.to_dict(),
    }


def _append(db: AsyncSession, package: KnowledgePackage, documents: list[dict], *, start: int) -> None:
    for ordinal, document in enumerate(documents, start=start):
        db.add(
            KnowledgePackageDocument(package_id=package.id, project_id=package.project_id, ordinal=ordinal, **document)
        )
