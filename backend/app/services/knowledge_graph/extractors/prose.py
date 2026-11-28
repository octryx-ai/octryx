"""LLM prose extractor for unstructured text."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.content_security.untrusted_fence import untrusted_section
from app.services.prompt_catalog import prompt_set_scope, render_prompt
from app.services.prompt_catalog.out_of_turn import scoped_prompt_set

from ..ontology import resolve_ontology
from ..store import add_claim, normalize_alias, upsert_edge, upsert_node
from .common import slugify

GenerateFn = Callable[[str], Awaitable[str]]

# Weak extraction models tend to emit generic role words as "person" entities;
# these are noise, not identities, and are dropped deterministically.
_GENERIC_PERSON_NAMES = {
    "admin", "administrator", "author", "co-author", "customer", "developer",
    "developers", "engineer", "engineers", "manager", "owner", "pm", "po",
    "reviewer", "team", "technician", "user", "users", "writer",
    "technician – writer", "product owner", "project manager",
}


def _is_noise_person(name: str) -> bool:
    normalized = " ".join(str(name or "").lower().split())
    return len(normalized) < 3 or normalized in _GENERIC_PERSON_NAMES


# Standalone generic nouns are meaningless as entities of ANY type ("Repository",
# "Service", ...) and pollute alias-based entity linking.
_GENERIC_ENTITY_NAMES = {
    "application", "base image", "build", "chart", "ci", "ci/cd", "cd",
    "cluster", "component", "components", "container", "database",
    "dependencies", "dependency", "deployment", "docker", "dockerfile",
    "document", "environment", "helm", "helm chart", "image", "images",
    "infrastructure", "k8s", "kubernetes", "libraries", "library", "module",
    "namespace", "pipeline", "pod", "project", "registry", "repo",
    "repository", "server", "service", "services", "stage", "stages",
    "system", "systems", "team", "terraform", "ticket", "tool", "version",
    "workflow",
}


def _is_generic_entity(name: str) -> bool:
    normalized = " ".join(str(name or "").lower().split())
    return normalized in _GENERIC_ENTITY_NAMES

# The JSON extraction ``_parse_extraction_json`` reads: fixed protocol, fills ``{answer_contract}``.
_JSON_CONTRACT = (
    'Return strict JSON: {"entities": [{"name": str, "type": str, "description": str}], '
    '"relations": [{"source": str, "target": str, "type": str, "description": str}], '
    '"claims": [{"subject": str, "statement": str, "type": str, '
    '"valid_from": str|null, "valid_until": str|null}]}.'
)


def build_extraction_prompt(text: str, ontology: dict[str, list[str]]) -> str:
    entity_types = ", ".join(ontology["entity_types"])
    relation_types = ", ".join(ontology["relation_types"])
    return render_prompt(
        "knowledge.graph.extraction",
        entity_types=entity_types,
        relation_types=relation_types,
        answer_contract=_JSON_CONTRACT,
        text=untrusted_section("source text", text.strip()[:6000], source="the knowledge source"),
    )


def build_gleaning_prompt(text: str, ontology: dict[str, list[str]], found_entities: list[str]) -> str:
    entity_types = ", ".join(ontology["entity_types"])
    relation_types = ", ".join(ontology["relation_types"])
    listed = ", ".join(found_entities[:60]) or "none"
    return render_prompt(
        "knowledge.graph.gleaning",
        listed=listed,
        entity_types=entity_types,
        relation_types=relation_types,
        answer_contract=_JSON_CONTRACT,
        text=untrusted_section("source text", text.strip()[:6000], source="the knowledge source"),
    )


def _gleaning_prompt(prompts: Any, text: str, ontology: dict[str, list[str]], found: list[str]) -> str:
    with prompt_set_scope(prompts):
        return build_gleaning_prompt(text, ontology, found)


def _parse_extraction_json(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"entities": [], "relations": [], "claims": []}
    if not isinstance(data, dict):
        return {"entities": [], "relations": [], "claims": []}
    return {
        "entities": data.get("entities") or [],
        "relations": data.get("relations") or [],
        "claims": data.get("claims") or [],
    }


class _GraphWriter:
    def __init__(self, db: AsyncSession, *, project_id: str | None, source_ref: str, ontology: dict[str, list[str]]):
        self.db = db
        self.project_id = project_id
        self.source_ref = source_ref
        self.allowed_entities = set(ontology["entity_types"])
        self.allowed_relations = set(ontology["relation_types"])
        self.node_by_name: dict[str, Any] = {}
        self.seen_relations: set[tuple[str, str, str]] = set()
        self.seen_claims: set[tuple[str, str]] = set()
        self.created_entities = self.created_relations = self.created_claims = 0

    async def apply(self, data: dict[str, Any]) -> int:
        added = await self._apply_entities(data["entities"])
        added += await self._apply_relations(data["relations"])
        added += await self._apply_claims(data["claims"])
        return added

    async def _apply_entities(self, entities: list[Any]) -> int:
        added = 0
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            name = str(entity.get("name") or "").strip()
            node_type = str(entity.get("type") or "").strip().lower()
            if not name or node_type not in self.allowed_entities:
                continue
            if node_type == "person" and _is_noise_person(name):
                continue
            if _is_generic_entity(name):
                continue
            if normalize_alias(name) in self.node_by_name:
                continue
            node = await upsert_node(
                self.db,
                project_id=self.project_id,
                node_type=node_type,
                node_key=slugify(name),
                display_name=name,
                description=str(entity.get("description") or "").strip(),
                source_refs=[self.source_ref],
            )
            self.node_by_name[normalize_alias(name)] = node
            self.created_entities += 1
            added += 1
        return added

    async def _apply_relations(self, relations: list[Any]) -> int:
        added = 0
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            relation_type = str(relation.get("type") or "").strip().lower()
            source = self.node_by_name.get(normalize_alias(relation.get("source")))
            target = self.node_by_name.get(normalize_alias(relation.get("target")))
            if relation_type not in self.allowed_relations or source is None or target is None:
                continue
            relation_key = (source.id, relation_type, target.id)
            if relation_key in self.seen_relations:
                continue
            self.seen_relations.add(relation_key)
            await upsert_edge(
                self.db,
                project_id=self.project_id,
                edge_type=relation_type,
                source_node_id=source.id,
                target_node_id=target.id,
                description=str(relation.get("description") or "").strip(),
                source_refs=[self.source_ref],
            )
            self.created_relations += 1
            added += 1
        return added

    async def _apply_claims(self, claims: list[Any]) -> int:
        added = 0
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            subject = self.node_by_name.get(normalize_alias(claim.get("subject")))
            statement = str(claim.get("statement") or "").strip()
            if subject is None or not statement:
                continue
            claim_key = (subject.id, statement.lower())
            if claim_key in self.seen_claims:
                continue
            self.seen_claims.add(claim_key)
            await add_claim(
                self.db,
                project_id=self.project_id,
                subject_node_id=subject.id,
                statement=statement,
                claim_type=str(claim.get("type") or "fact").strip().lower() or "fact",
                valid_from_label=(str(claim.get("valid_from")).strip() or None)
                if claim.get("valid_from")
                else None,
                valid_until_label=(str(claim.get("valid_until")).strip() or None)
                if claim.get("valid_until")
                else None,
                source_refs=[self.source_ref],
            )
            self.created_claims += 1
            added += 1
        return added


async def extract_graph_from_text(
    db: AsyncSession,
    *,
    project_id: str | None,
    text: str,
    source_ref: str,
    generate: GenerateFn,
    project: Any = None,
    gleaning_rounds: int = 1,
) -> dict[str, Any]:
    """LLM extraction constrained to the ontology, with gleaning and claims."""
    ontology = resolve_ontology(project)
    writer = _GraphWriter(db, project_id=project_id, source_ref=source_ref, ontology=ontology)

    async with scoped_prompt_set(db, workspace_id=project_id) as prompts:
        extraction_prompt = build_extraction_prompt(text, ontology)
    await writer.apply(_parse_extraction_json(await generate(extraction_prompt)))

    for _round in range(max(0, int(gleaning_rounds))):
        found = [node.display_name for node in writer.node_by_name.values()]
        gleaned = _parse_extraction_json(
            await generate(_gleaning_prompt(prompts, text, ontology, found))
        )
        if await writer.apply(gleaned) == 0:
            break

    return {"entities": writer.created_entities, "relations": writer.created_relations, "claims": writer.created_claims}
