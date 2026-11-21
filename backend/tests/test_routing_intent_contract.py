"""Cross-layer routing intent contract tests.

Drift protection for the layered routing design:

- ``services/execution_strategy_service.ROUTING_INTENTS`` is the authoritative
  set of routing intents.
- ``services/workflow_routing_policies._WORKFLOW_ID_ROUTING_INTENT_MAP`` is the
  single workflow-id-to-intent map, so it is the one to pin.

These tests are pure-import contract checks: deterministic, no DB, no network.
"""

from __future__ import annotations

import importlib.util

from app.services.execution_strategy_intent import ROUTING_INTENTS
from app.services.workflow_routing.policy_intent import _SUPPORTED_ROUTING_INTENTS, _WORKFLOW_ID_ROUTING_INTENT_MAP


def test_every_policy_mapped_intent_is_a_known_routing_intent() -> None:
    unknown = {
        workflow_id: intent
        for workflow_id, intent in _WORKFLOW_ID_ROUTING_INTENT_MAP.items()
        if intent not in ROUTING_INTENTS
    }
    assert not unknown, (
        "workflow_routing_policies._WORKFLOW_ID_ROUTING_INTENT_MAP maps to intents that are "
        f"not in execution_strategy_service.ROUTING_INTENTS: {sorted(unknown.items())}"
    )


def test_policy_supported_intents_match_strategy_service_intents() -> None:
    assert _SUPPORTED_ROUTING_INTENTS == set(ROUTING_INTENTS), (
        "workflow_routing_policies._SUPPORTED_ROUTING_INTENTS drifted from "
        "execution_strategy_service.ROUTING_INTENTS: "
        f"only_in_policy={sorted(_SUPPORTED_ROUTING_INTENTS - ROUTING_INTENTS)}, "
        f"only_in_strategy={sorted(ROUTING_INTENTS - _SUPPORTED_ROUTING_INTENTS)}"
    )


def test_pre_turn_llm_router_module_stays_removed() -> None:
    # A second intent map (and its direct provider call) must not come back.
    assert importlib.util.find_spec("app.services.llm_router") is None
