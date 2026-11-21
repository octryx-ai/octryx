"""The catalog-backed services prompt builders render byte-identical prompts from the seeded catalog.

Request analysis, the bounded AWS read, person research, AWS topology detail selection, research
tasks and literature constraints, delegated child agents, coordinator continues, the governed
coding execution prompt and verification lines, tool guards, the current-step contract, the tool
working set and compact AWS guidance, for the fixed inputs of
``tests/prompt_catalog_services_scenarios_support.py``, pinned as digests.
"""

from __future__ import annotations

from tests.prompt_catalog_services_scenarios import SCENARIOS
from tests.prompt_catalog_services_scenarios_support import scenario_digests


def test_the_services_builders_render_what_they_rendered_before_the_migration() -> None:
    digests = scenario_digests()
    assert sorted(digests) == sorted(SCENARIOS)
    assert [name for name, digest in digests.items() if SCENARIOS[name] != digest] == []
