"""Graph extraction profiles are validated data, and the data reproduces today's prompts exactly."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.services.content_security.model_call_scope import session_call
from app.services.knowledge.eval import change_typing
from app.services.knowledge.temporal.change_types import (
    ACTION_REQUIRED_TYPES,
    CHANGE_EDGE_TYPES,
    CHANGE_RECORDS_PROFILE,
    CURRENT_PROFILES,
    NOT_A_CHANGE_RELATION,
    change_instructions,
)
from app.services.knowledge.temporal.extraction_profiles import (
    PROFILE_DIR,
    ExtractionProfileError,
    build_catalog,
    extraction_profiles,
    select_profile,
)
from app.services.knowledge.temporal.graphiti_adapters import RefusingCrossEncoder
from app.services.knowledge.temporal.graphiti_boundary import (
    EntityNode,
    EpisodeType,
    EpisodicNode,
    GraphitiClients,
    NoOpTracer,
    extract_edges,
)
from app.services.knowledge.temporal.graphiti_llm import GovernedGraphitiLLM

GOLDEN = json.loads((Path(__file__).parents[2] / "fixtures" / "knowledge_extraction_profiles_golden.json").read_text())


class _RecordingProvider:
    def __init__(self, seen: list[str]) -> None:
        self._seen = seen

    async def chat(self, *, messages, **options):
        self._seen.append(messages[-1]["content"])
        return {"content": json.dumps({"edges": []}), "usage": {}}


async def _edge_prompt_sha256(monkeypatch, profile) -> str:
    seen: list[str] = []
    monkeypatch.setattr("app.agent.providers.get_provider", lambda **runtime: _RecordingProvider(seen))
    llm = GovernedGraphitiLLM([{"provider_name": "fake", "model": "m"}], scope=session_call(None), check_change_edges=profile.self_check)
    clients = GraphitiClients(
        driver=change_typing._NoGraph(), llm_client=llm, embedder=change_typing._NoEmbedder(),
        cross_encoder=RefusingCrossEncoder(), tracer=NoOpTracer(),
    )
    when = datetime(2026, 9, 30, tzinfo=UTC)
    episode = EpisodicNode(name="s", group_id="spring-boot", labels=[], source=EpisodeType.text,
                           source_description="Spring Boot 4.0 Migration Guide (version 4.0)",
                           content="Spring Boot 4.0 requires Java 17 or later.", created_at=when, valid_at=when)
    nodes = [EntityNode(name=name, group_id="spring-boot", labels=["Entity"], created_at=when)
             for name in ("Spring Boot 4.0", "Java 17")]
    await extract_edges(clients, episode, nodes, [], {("Entity", "Entity"): list(profile.edge_types or ())},
                        "spring-boot", profile.edge_types, profile.instructions("spring-boot", "4.0"))
    return hashlib.sha256(seen[0].encode()).hexdigest()


async def test_the_data_profiles_render_todays_prompts_and_edge_types_byte_for_byte(monkeypatch):
    profiles = extraction_profiles()
    assert CHANGE_RECORDS_PROFILE == "change-records-v2"
    assert sorted(CURRENT_PROFILES) == GOLDEN["current_profiles"] == sorted(profiles)
    assert NOT_A_CHANGE_RELATION == GOLDEN["not_a_change_relation"]
    for profile_id in GOLDEN["current_profiles"]:
        golden, profile = GOLDEN[profile_id], profiles[profile_id]
        rendered = [
            {"name": name, "class": model.__name__, "description": model.__doc__, "fields": sorted(model.model_fields)}
            for name, model in (profile.edge_types or {}).items()
        ]
        assert rendered == golden["edge_types"]
        assert sorted(profile.action_required_types) == golden["action_required"]
        assert profile.self_check is golden["self_check"]
        if golden["instructions"] is None:
            assert profile.instructions("spring-boot", "4.0") is None
        else:
            for pair, text in golden["instructions"].items():
                product, version = pair.split("|")
                assert profile.instructions(product, version) == text
        assert await _edge_prompt_sha256(monkeypatch, profile) == golden["edge_prompt_sha256"]
    typed = profiles[CHANGE_RECORDS_PROFILE]
    assert CHANGE_EDGE_TYPES is typed.edge_types and ACTION_REQUIRED_TYPES == typed.action_required_types
    assert change_instructions("spring-boot", "4.0") == GOLDEN[CHANGE_RECORDS_PROFILE]["instructions"]["spring-boot|4.0"]
    assert select_profile(("spring-boot",), "4.0").profile_id == CHANGE_RECORDS_PROFILE
    assert select_profile(("spring-boot",), None).profile_id == "generic-v1"
    assert select_profile((), None).profile_id == "generic-v1"


def _profile(**overrides) -> dict:
    profile = {
        "key": "shipping-changes",
        "version": 1,
        "title": "Shipping protocol specification changes",
        "applies_to": {"revisions": "versioned_product", "products": ["shipping-protocol"]},
        "self_check": False,
        "edge_types": [
            {"name": "MANDATES", "model": "Mandates", "action_required": True, "description": "A new obligation."}
        ],
        "instructions": ["The text is the {product} specification version {version}."],
    }
    profile.update(overrides)
    return profile


def _catalog(tmp_path: Path, *documents: str) -> dict:
    paths = [PROFILE_DIR / "change_records.json", PROFILE_DIR / "generic.json"]
    for index, document in enumerate(documents):
        path = tmp_path / f"extra_{index}.json"
        path.write_text(document, encoding="utf-8")
        paths.append(path)
    return build_catalog(paths)


def test_a_new_domain_profile_is_a_data_change_and_malformed_profiles_are_refused(tmp_path):
    catalog = _catalog(tmp_path, json.dumps(_profile()))
    domain = select_profile(("shipping-protocol",), "2.3.1", catalog)
    assert domain.profile_id == "shipping-changes-v1" and list(domain.edge_types) == ["MANDATES"]
    assert domain.instructions("shipping-protocol", "2.3.1") == "The text is the shipping-protocol specification version 2.3.1."
    assert select_profile(("spring-boot",), "4.0", catalog).profile_id == CHANGE_RECORDS_PROFILE
    assert select_profile(("shipping-protocol",), None, catalog).profile_id == "generic-v1"

    refused = [
        json.dumps({**_profile(), "extra": 1}),
        json.dumps({key: value for key, value in _profile().items() if key != "self_check"}),
        json.dumps(_profile()).replace('"version": 1', '"version": 1, "version": 2'),
        json.dumps(_profile(key="change-records")),
        json.dumps(_profile(applies_to={"revisions": "versioned_product", "products": []})),
        json.dumps(_profile(instructions=["{product} {document}"])),
        json.dumps(_profile(instructions=["{product!r}"])),
        json.dumps(_profile(applies_to={"revisions": "any", "products": ["shipping-protocol"]}, self_check=True)),
        json.dumps(_profile(edge_types=[{"name": "MANDATES", "model": "Mandates", "action_required": "yes",
                                         "description": "x"}])),
    ]
    for document in refused:
        with pytest.raises(ExtractionProfileError):
            _catalog(tmp_path, document)
    with pytest.raises(ExtractionProfileError):
        _catalog(tmp_path, json.dumps(_profile()), json.dumps(_profile(key="shipping-other")))
    with pytest.raises(ExtractionProfileError):
        build_catalog([PROFILE_DIR / "change_records.json"])
