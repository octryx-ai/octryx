"""The judge prompt surfaces render byte-identical prompts from the seeded catalog.

For the fixed inputs of ``tests/prompt_catalog_judge_scenarios_support.py``, the pinned digests.
"""

from __future__ import annotations

from tests.prompt_catalog_golden_keys_judge import SCENARIOS
from tests.prompt_catalog_judge_scenarios_support import judge_digests


def test_the_judge_prompts_render_what_they_rendered_before_the_migration() -> None:
    digests = judge_digests()
    assert sorted(digests) == sorted(SCENARIOS)
    assert [name for name, digest in digests.items() if SCENARIOS[name] != digest] == []
