"""The answer prompt surfaces render byte-identical prompts from the seeded catalog.

For the fixed inputs of ``tests/prompt_catalog_answer_scenarios_support.py``, the pinned digests.
"""

from __future__ import annotations

from tests.prompt_catalog_answer_scenarios_support import answer_digests
from tests.prompt_catalog_golden_keys_answer import SCENARIOS


def test_the_answer_prompts_render_what_they_rendered_before_the_migration() -> None:
    digests = answer_digests()
    assert sorted(digests) == sorted(SCENARIOS)
    assert [name for name, digest in digests.items() if SCENARIOS[name] != digest] == []
