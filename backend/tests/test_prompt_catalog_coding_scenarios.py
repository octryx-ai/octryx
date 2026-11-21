"""The coding call sites render byte-identical prompts from the seeded catalog.

TDD reminders and phases, the coding workflow agent definitions, upgrade gate states and
the migration quality reminders, for the fixed inputs of
``tests/prompt_catalog_coding_scenarios_support.py``, pinned as digests.
"""

from __future__ import annotations

from tests.prompt_catalog_coding_scenarios_support import coding_scenario_digests
from tests.prompt_catalog_golden_keys_coding import SCENARIOS


def test_the_coding_builders_render_what_they_rendered_before_the_migration() -> None:
    digests = coding_scenario_digests()
    assert sorted(digests) == sorted(SCENARIOS)
    assert [name for name, digest in digests.items() if SCENARIOS[name] != digest] == []
