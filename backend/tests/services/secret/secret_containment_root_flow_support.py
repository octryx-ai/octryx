"""Shared helpers for the test_secret_containment_root_flow_* modules."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from secret_containment import contract, env_scan  # noqa: E402

# Invented fixture value: 32 repeated characters, never a real credential.
FAKE_MATERIAL = "a" * 32


def _findings(findings: list[contract.Finding]) -> list[tuple[str, int, str, str]]:
    return [(finding.path, finding.line, finding.key, finding.reason) for finding in findings]


def _scan(text: str) -> list[tuple[str, int, str, str]]:
    return _findings(env_scan.scan_secret_manifest("secrets.yaml", text))
