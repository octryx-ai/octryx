"""The knowledge prompt surfaces render byte-identical prompts from the seeded catalog."""

from __future__ import annotations

from tests.services.prompt_catalog.prompt_catalog_golden_keys_knowledge import SCENARIOS
from tests.services.prompt_catalog.prompt_catalog_knowledge_scenarios_support import knowledge_digests


def test_the_knowledge_prompts_render_what_they_rendered_before_the_migration() -> None:
    digests = knowledge_digests()
    assert sorted(digests) == sorted(SCENARIOS)
    assert [name for name, digest in digests.items() if SCENARIOS[name] != digest] == []
