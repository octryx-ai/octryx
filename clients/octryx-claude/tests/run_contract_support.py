"""Shared helpers for the test_run_contract_* modules."""

from __future__ import annotations

RUN = "3f2a9c1e-5b4d-4e6f-8a7b-9c0d1e2f3a4b"


def _contract(**overrides) -> dict:
    contract = {
        "version": 2, "digest": "sha256:one",
        "run": {"id": RUN, "workflow_key": "bug-fix-reproduction", "status": "running"},
        "phase": {"title": "Minimal fix", "capability_class": "change", "protected_files": ["tests/test_totals.py"]},
        "loop": [{"title": "Fix ↔ test", "iteration": 2, "of": 4}],
        "facts": {"base_sha": None}, "waiting": None, "paused": None,
    }
    return {**contract, **overrides}
