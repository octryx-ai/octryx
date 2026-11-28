"""Workflow prompts rendered from the seeded catalog match their pinned digests."""

from __future__ import annotations

from hashlib import sha256

from tests.services.prompt_catalog.prompt_catalog_golden_keys_workflow import SCENARIOS
from tests.services.prompt_catalog.prompt_catalog_workflow_scenarios_support import scenario_outputs


def test_every_workflow_scenario_renders_the_pinned_bytes() -> None:
    digests = {name: sha256(text.encode("utf-8")).hexdigest() for name, text in scenario_outputs().items()}
    assert digests == SCENARIOS
