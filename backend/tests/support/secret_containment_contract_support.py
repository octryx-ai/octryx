"""Synthetic fixture values, the weak-default chart template and helpers shared by the test_secret_containment_* modules split from test_secret_containment_contract.py."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from secret_containment import contract  # noqa: E402

# Invented fixture value: 32 repeated characters, never a real credential.
FAKE_MATERIAL = "a" * 32


# A chart template with the same weak-default shape as the real chart.
TEMPLATE_WITH_WEAK_DEFAULTS = """{{- $sec := .Values.secrets -}}
apiVersion: v1
kind: Secret
metadata:
  name: fixture-secrets
type: Opaque
data:
  JWT_SECRET: {{ $sec.jwtSecret | default "d2Vhaw==" | quote }}
  ADMIN_DEFAULT_PASSWORD: {{ $sec.adminPassword | default "d2Vhaw==" | quote }}
  OPENROUTER_API_KEY: {{ $sec.openRouterApiKey | default "" | quote }}
"""


def _reasons(findings: list[contract.Finding]) -> list[tuple[str, str]]:
    return [(finding.key, finding.reason) for finding in findings]


# The keys the fixture template would otherwise default, held by valid placeholders.
COMPLIANT_FIXTURE_VALUES = (
    "replicaCount: 1\n"
    "secrets:\n"
    '  jwtSecret: "REPLACE_WITH_BASE64_JWT_SECRET"\n'
    '  adminPassword: "REPLACE_WITH_BASE64_ADMIN_PASSWORD"\n'
)


def _chart(tmp_path: Path, *, helmignore: str | None = "*.local.yaml\n*.local.yml\n", values: str | None = None) -> Path:
    chart = tmp_path / "fixture-chart"
    (chart / "templates").mkdir(parents=True)
    (chart / "Chart.yaml").write_text("apiVersion: v2\nname: fixture\nversion: 0.1.0\n", encoding="utf-8")
    (chart / "values.yaml").write_text(COMPLIANT_FIXTURE_VALUES if values is None else values, encoding="utf-8")
    (chart / "templates" / "secrets.yaml").write_text(TEMPLATE_WITH_WEAK_DEFAULTS, encoding="utf-8")
    if helmignore is not None:
        (chart / ".helmignore").write_text(helmignore, encoding="utf-8")
    return chart


SECRET_MANIFEST = """apiVersion: v1
kind: Secret
metadata:
  name: fixture-secrets
  namespace: fixture
type: Opaque
stringData:
  JWT_SECRET: "{value}"
  OPENROUTER_API_KEY: ""
"""
