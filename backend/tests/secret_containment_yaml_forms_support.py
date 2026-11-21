"""Shared fake material, required keys and finding helper for the YAML form containment tests."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from secret_containment import contract  # noqa: E402

# Invented fixture value: 32 repeated characters, never a real credential.
FAKE_MATERIAL = "a" * 32


REQUIRED_JWT = {"jwtsecret": "jwtSecret"}


def _findings(findings: list[contract.Finding]) -> list[tuple[str, int, str, str]]:
    return [(finding.path, finding.line, finding.key, finding.reason) for finding in findings]
