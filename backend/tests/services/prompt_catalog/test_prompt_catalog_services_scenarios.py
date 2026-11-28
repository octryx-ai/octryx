"""The catalog-backed services prompt builders render byte-identical prompts from the seeded catalog."""

from __future__ import annotations

from tests.services.prompt_catalog.prompt_catalog_services_scenarios import SCENARIOS
from tests.services.prompt_catalog.prompt_catalog_services_scenarios_support import scenario_digests


def test_the_services_builders_render_what_they_rendered_before_the_migration() -> None:
    digests = scenario_digests()
    assert sorted(digests) == sorted(SCENARIOS)
    assert [name for name, digest in digests.items() if SCENARIOS[name] != digest] == []
