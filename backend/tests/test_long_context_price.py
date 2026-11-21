"""A long prompt is charged at the model's long-prompt rate card: Haiku 5.5 costs 5x every rate when the prompt
exceeds 100K tokens, so a run with many such calls would otherwise show about half its cost."""

from __future__ import annotations

import pytest

from app.services.model_catalog.contract import ModelCatalogError
from app.services.model_catalog.cost import gateway_cost_contract
from app.services.model_gateway.inbound.transcript_cost import _cache_aware_catalog_cost
from app.services.model_gateway.litellm.alias_catalog import _resolve_cost_contract

HAIKU = {"source": "catalog_pricing", "input_per_million_usd": 0.11, "output_per_million_usd": 0.55,
         "cache_read_per_million_usd": 0.011, "cache_write_per_million_usd": 0.1375,
         "long_context_threshold_tokens": 100_000, "long_context_factor": 5}


class _Entry:
    def __init__(self, cost):
        self.cost = cost


def _contract(raw):
    contract, denial = _resolve_cost_contract(raw)
    assert not denial, denial
    return contract


def test_a_prompt_over_the_threshold_costs_the_factor_times():
    entry = _Entry(_contract(HAIKU))
    short = {"input_tokens": 1000, "cache_read_input_tokens": 90_000, "cache_creation_input_tokens": 5000,
             "output_tokens": 2000}
    long = {**short, "cache_read_input_tokens": 140_000}
    base = (1000 * 0.11 + 90_000 * 0.011 + 5000 * 0.1375 + 2000 * 0.55) / 1e6
    assert _cache_aware_catalog_cost(entry, short) == pytest.approx(base)
    assert _cache_aware_catalog_cost(entry, long) == pytest.approx(
        5 * (1000 * 0.11 + 140_000 * 0.011 + 5000 * 0.1375 + 2000 * 0.55) / 1e6)
    plain = _Entry(_contract({key: value for key, value in HAIKU.items() if not key.startswith("long_")}))
    assert _cache_aware_catalog_cost(plain, long) == pytest.approx(
        (1000 * 0.11 + 140_000 * 0.011 + 5000 * 0.1375 + 2000 * 0.55) / 1e6)


def test_the_long_prompt_pair_is_validated_on_both_sides():
    assert _resolve_cost_contract({**HAIKU, "long_context_factor": 0.5})[0] is None
    assert _resolve_cost_contract({**HAIKU, "long_context_threshold_tokens": None})[0] is None
    tab = {"cost_source": "catalog_pricing", "pricing_input": 0.11, "pricing_output": 0.55,
           "pricing_cache_read": 0.011, "pricing_cache_write": 0.1375,
           "long_context_threshold_tokens": 100_000, "long_context_factor": 5}
    assert gateway_cost_contract(tab)["long_context_factor"] == 5.0
    with pytest.raises(ModelCatalogError):
        gateway_cost_contract({**tab, "long_context_threshold_tokens": "100k"})
