"""Graph extraction's model path: the engine's sampling rule, ``extract``-tagged runtimes, then the Workspace's
alias admission policy; without either, ``graph_model_unconfigured`` and no model call."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.models import Project
from app.services.content_security.model_call_scope import session_call
from app.services.knowledge.temporal.errors import GraphModelUnavailableError
from app.services.knowledge.temporal.graph_model_selection import REASON_UNCONFIGURED, select_graph_runtimes
from app.services.knowledge.temporal.graphiti_llm import GovernedGraphitiLLM
from tests.knowledge_evidence_seed_support import seed_workspace

ALIAS_A, ALIAS_B, ALIAS_C, ALIAS_D = "graph-alias-a", "graph-alias-b", "graph-alias-c", "graph-alias-d"
DIRECT_BEDROCK = {"provider_name": "bedrock", "driver": "bedrock_api", "model": "qwen.qwen3-32b-v1:0",
                  "target_id": "direct", "priority": 1, "use_case_tags": [], "config_json": {}}


def _gateway(alias: str, *, priority: int, tags: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"provider_name": "graph-gateway", "driver": "litellm_gateway", "model": alias,
            "target_id": f"target-{alias}", "priority": priority, "use_case_tags": list(tags), "config_json": {}}


class _Recording:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **_runtime: Any) -> Any:
        recording = self

        class _Client:
            async def chat(self, **options: Any) -> dict[str, Any]:
                recording.calls.append(options)
                return {"content": json.dumps({"ok": True}), "usage": {}}

        return _Client()


async def test_graph_extraction_follows_the_sampling_capability_rule(monkeypatch):
    recording = _Recording()
    monkeypatch.setattr("app.agent.providers.get_provider", recording)
    messages = [SimpleNamespace(role="user", content="x")]
    claude_4_5 = {"provider_name": "bedrock", "model": "anthropic.claude-sonnet-4-5-20250929-v1:0"}
    claude_5 = {"provider_name": "bedrock", "model": "anthropic.claude-opus-5-5"}

    await GovernedGraphitiLLM([claude_4_5], scope=session_call(None))._generate_response(messages)
    assert recording.calls[-1]["temperature"] == 0.0
    await GovernedGraphitiLLM([claude_4_5], scope=session_call(None), temperature=0.2)._generate_response(messages)
    assert recording.calls[-1]["temperature"] == 0.2

    await GovernedGraphitiLLM([claude_5], scope=session_call(None))._generate_response(messages)
    assert "temperature" not in recording.calls[-1]
    await GovernedGraphitiLLM([claude_5], scope=session_call(None), temperature=0.2)._generate_response(messages)
    assert "temperature" not in recording.calls[-1]

    await GovernedGraphitiLLM([{**claude_4_5, "accepts_temperature": False}], scope=session_call(None))._generate_response(messages)
    assert "temperature" not in recording.calls[-1]
    await GovernedGraphitiLLM([{**claude_5, "accepts_temperature": True}], scope=session_call(None))._generate_response(messages)
    assert recording.calls[-1]["temperature"] == 0.0


async def _workspace(db, model_policy: dict[str, Any] | None) -> str:
    workspace_id = await seed_workspace(db)
    project = await db.get(Project, workspace_id)
    project.config = {} if model_policy is None else {"model_policy": model_policy}
    await db.commit()
    return workspace_id


def _resolver(runtimes: list[dict[str, Any]]):
    async def resolve(_db, **_options: Any) -> list[dict[str, Any]]:
        return [dict(runtime) for runtime in runtimes]

    return resolve


# Runtime priority order: direct Bedrock first, then A, B, C, D.
RUNTIMES = [DIRECT_BEDROCK, _gateway(ALIAS_A, priority=2), _gateway(ALIAS_B, priority=3),
            _gateway(ALIAS_C, priority=4), _gateway(ALIAS_D, priority=5)]


async def _chosen(db, model_policy: dict[str, Any] | None, runtimes=RUNTIMES) -> list[str]:
    workspace_id = await _workspace(db, model_policy)
    chosen = await select_graph_runtimes(db, project_id=workspace_id, resolve_runtimes=_resolver(runtimes))
    return [runtime["model"] for runtime in chosen]


async def test_runtimes_tagged_extract_win_over_the_workspace_policy(db):
    tagged = {**DIRECT_BEDROCK, "target_id": "tagged", "model": "tagged-model", "use_case_tags": ["Extract"]}
    assert await _chosen(db, {"allowed_aliases": [ALIAS_A]}, [*RUNTIMES, tagged]) == ["tagged-model"]


async def test_allowed_aliases_are_used_in_their_own_order_and_never_a_direct_target(db):
    # Granted C then A: that order, not runtime priority; B and D are not granted; Bedrock never.
    assert await _chosen(db, {"allowed_aliases": [ALIAS_C, ALIAS_A]}) == [ALIAS_C, ALIAS_A]


async def test_allow_all_appends_the_other_admitted_aliases_by_priority_and_a_denied_alias_is_excluded(db):
    policy = {"allowed_aliases": [ALIAS_C, ALIAS_B], "denied_aliases": [ALIAS_B, ALIAS_A],
              "allow_all_admitted_aliases": True}
    # B is granted and denied: the denial wins. A is denied. D comes from allow-all, after the grants.
    assert await _chosen(db, policy) == [ALIAS_C, ALIAS_D]


async def test_without_a_tag_or_an_admitting_workspace_policy_graph_extraction_needs_configuration(db):
    for policy in (None, {"allowed_aliases": ["unknown-alias"]}, {"denied_aliases": [ALIAS_A]}):
        workspace_id = await _workspace(db, policy)
        with pytest.raises(GraphModelUnavailableError) as refused:
            await select_graph_runtimes(db, project_id=workspace_id, resolve_runtimes=_resolver(RUNTIMES))
        assert (refused.value.state, refused.value.reason) == ("needs_configuration", REASON_UNCONFIGURED)
    # Only direct targets: never picked, also when the Workspace grants everything.
    workspace_id = await _workspace(db, {"allow_all_admitted_aliases": True})
    with pytest.raises(GraphModelUnavailableError) as refused:
        await select_graph_runtimes(db, project_id=workspace_id, resolve_runtimes=_resolver([DIRECT_BEDROCK]))
    assert refused.value.reason == REASON_UNCONFIGURED
