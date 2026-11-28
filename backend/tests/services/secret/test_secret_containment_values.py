"""Synthetic tests for the secret containment scanners."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from secret_containment import contract, tracked_scan, values_scan  # noqa: E402

from tests.support.secret_containment_contract_support import FAKE_MATERIAL, _chart, _reasons  # noqa: E402


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", contract.EMPTY),
        ("REPLACE_WITH_BASE64_JWT_SECRET", contract.PLACEHOLDER),
        ("<base64-encoded>", contract.PLACEHOLDER),
        ("${JWT_SECRET}", contract.PLACEHOLDER),
        ("{{ .Values.jwtSecret }}", contract.REFERENCE),
        ("changeme", contract.WEAK),
        ("changeme-32-chars-minimum-here", contract.WEAK),
        ("admin", contract.WEAK),
        (FAKE_MATERIAL, contract.MATERIAL),
        ("false", contract.MATERIAL),
        ("123456", contract.MATERIAL),
    ],
)
def test_value_classification(value: str, expected: str) -> None:
    assert contract.classify_value(value) == expected


def test_non_placeholder_secret_block_value_is_reported() -> None:
    content = f'secrets:\n  generateSecrets: false\n  jwtSecret: "{FAKE_MATERIAL}"\n'
    assert _reasons(values_scan.scan_values_file("values.yaml", content)) == [
        ("jwtSecret", contract.REASON_BLOCK_NOT_PLACEHOLDER)
    ]


def test_block_scalar_for_a_secret_key_is_reported() -> None:
    content = "secrets:\n  jwtSecret: |\n    not-a-placeholder\n"
    assert _reasons(values_scan.scan_values_file("values.yaml", content)) == [
        ("jwtSecret", contract.REASON_BLOCK_SCALAR)
    ]


def test_weak_known_value_is_not_accepted_as_a_placeholder() -> None:
    content = "secrets:\n  adminPassword: changeme\n"
    assert _reasons(values_scan.scan_values_file("values.yaml", content)) == [
        ("adminPassword", contract.REASON_WEAK_VALUE)
    ]


def test_empty_secret_value_is_reported_when_the_chart_substitutes_a_weak_default() -> None:
    content = 'secrets:\n  jwtSecret: ""\n'
    weak_keys = frozenset({"jwtsecret"})
    assert _reasons(values_scan.scan_values_file("values.yaml", content, weak_keys)) == [
        ("jwtSecret", contract.REASON_EMPTY_WEAK_DEFAULT)
    ]


def test_empty_secret_value_passes_without_a_weak_chart_default() -> None:
    content = 'secrets:\n  openRouterApiKey: ""\n'
    assert values_scan.scan_values_file("values.yaml", content, frozenset({"jwtsecret"})) == []


def test_weak_default_keys_are_read_from_the_chart_templates(tmp_path: Path) -> None:
    chart = _chart(tmp_path)
    weak_keys = values_scan.weak_default_secret_keys(chart)
    assert "jwtsecret" in weak_keys
    assert "adminpassword" in weak_keys
    # The template default for this key is empty, so an empty value stays inert.
    assert "openrouterapikey" not in weak_keys


def test_placeholder_secret_block_values_pass() -> None:
    content = (
        "secrets:\n"
        '  jwtSecret: "REPLACE_WITH_BASE64_JWT_SECRET"\n'
        "  encryptionKey: <base64-encoded>\n"
        "  postgresPassword: {{ .Values.global.postgresPassword }}\n"
    )
    assert values_scan.scan_values_file("values.yaml", content, frozenset({"jwtsecret"})) == []


def test_missing_secret_key_with_a_weak_chart_default_is_reported() -> None:
    required = {"jwtsecret": "jwtSecret", "adminpassword": "adminPassword"}
    content = 'secrets:\n  jwtSecret: "REPLACE_WITH_BASE64_JWT_SECRET"\n'
    assert _reasons(values_scan.scan_values_file("values.yaml", content, required, required)) == [
        ("adminPassword", contract.REASON_MISSING_WEAK_DEFAULT)
    ]


def test_missing_secret_block_reports_every_key_the_chart_would_default() -> None:
    required = {"jwtsecret": "jwtSecret", "adminpassword": "adminPassword"}
    findings = values_scan.scan_values_file("values.yaml", "replicaCount: 1\n", required, required)
    assert _reasons(findings) == [
        ("adminPassword", contract.REASON_MISSING_WEAK_DEFAULT),
        ("jwtSecret", contract.REASON_MISSING_WEAK_DEFAULT),
    ]


def test_required_secret_key_must_be_declared_inside_the_secret_block() -> None:
    required = {"jwtsecret": "jwtSecret"}
    content = 'config:\n  jwtSecret: "REPLACE_WITH_BASE64_JWT_SECRET"\n'
    assert _reasons(values_scan.scan_values_file("values.yaml", content, required, required)) == [
        ("jwtSecret", contract.REASON_MISSING_WEAK_DEFAULT)
    ]


def test_declared_required_key_passes_when_it_holds_a_template_reference() -> None:
    required = {"jwtsecret": "jwtSecret"}
    content = "secrets:\n  jwtSecret: {{ .Values.global.jwtSecret }}\n"
    assert values_scan.scan_values_file("values.yaml", content, required, required) == []


def test_weak_default_keys_report_the_spelling_the_chart_template_uses(tmp_path: Path) -> None:
    assert values_scan.weak_default_secret_keys(_chart(tmp_path))["jwtsecret"] == "jwtSecret"


def test_only_the_authoritative_values_file_must_declare_every_required_key(tmp_path: Path) -> None:
    chart = _chart(tmp_path)
    (chart / "values.eks.yaml").write_text(
        'secrets:\n  jwtSecret: "REPLACE_WITH_BASE64_JWT_SECRET"\n', encoding="utf-8"
    )
    assert tracked_scan.check_paths(chart, ["values.eks.yaml"]) == []
    assert tracked_scan.check_paths(chart, ["values.yaml"]) == []


def test_dropping_a_required_key_from_the_authoritative_values_file_is_reported(tmp_path: Path) -> None:
    chart = _chart(tmp_path, values='secrets:\n  jwtSecret: "REPLACE_WITH_BASE64_JWT_SECRET"\n')
    assert _reasons(tracked_scan.check_paths(chart, ["values.yaml"])) == [
        ("adminPassword", contract.REASON_MISSING_WEAK_DEFAULT)
    ]


def test_secret_material_key_outside_a_secret_block_is_reported() -> None:
    content = f'config:\n  jwtSecret: "{FAKE_MATERIAL}"\n'
    assert _reasons(values_scan.scan_values_file("values.yaml", content)) == [
        ("jwtSecret", contract.REASON_NOT_PLACEHOLDER)
    ]


def test_secret_reference_keys_are_not_flagged() -> None:
    content = "externalSecrets:\n  secretName: octryx-secrets\n  tokenKey: token\n"
    assert values_scan.scan_values_file("values.yaml", content) == []


def test_known_non_secret_configuration_in_secret_block_is_allowed() -> None:
    assert values_scan.scan_values_file("values.yaml", "secrets:\n  generateSecrets: false\n") == []


def test_finding_output_never_contains_the_value() -> None:
    content = f'secrets:\n  jwtSecret: "{FAKE_MATERIAL}"\n'
    findings = values_scan.scan_values_file("values.yaml", content)
    assert findings
    for finding in findings:
        assert FAKE_MATERIAL not in finding.render()
