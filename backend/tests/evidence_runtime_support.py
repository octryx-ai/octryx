"""The ``evidence`` scenario on the harness parity turn.
``_evidence_scenario`` is autouse for a module that imports it."""

from __future__ import annotations

from typing import Any

import pytest

# The parity scenarios table is keyed by name; the evidence scenario's script is set per test.
_SCENARIO_OVERRIDES: dict[str, Any] = {}


@pytest.fixture(autouse=True)
def _evidence_scenario(monkeypatch):
    from tests import test_harness_runtime_parity as parity

    class _Scenarios(dict):
        def __getitem__(self, key):
            if key == "evidence":
                return {}, list(_SCENARIO_OVERRIDES.get("script") or [])
            return super().__getitem__(key)

    monkeypatch.setattr(parity, "SCENARIOS", _Scenarios(parity.SCENARIOS))
    yield
    _SCENARIO_OVERRIDES.clear()
