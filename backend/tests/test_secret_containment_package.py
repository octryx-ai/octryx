"""The chart package check: helmignore, chart root files, values files and the checker CLI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from secret_containment import contract, package_scan  # noqa: E402

from tests.secret_containment_contract_support import FAKE_MATERIAL, SECRET_MANIFEST, _chart, _reasons  # noqa: E402

PACKAGE_CHECKER = REPO_ROOT / "scripts" / "check_chart_package_inputs.py"


# ── chart package inputs ───────────────────────────────────────────────────────


def test_clean_chart_directory_has_no_findings(tmp_path: Path) -> None:
    chart = _chart(tmp_path)
    (chart / "README.md").write_text("# fixture\n", encoding="utf-8")
    assert package_scan.check_chart_directory(chart) == []


@pytest.mark.parametrize("name", ["values-local.yaml", "values.dev.yaml", "secrets.yaml", "values.local.yaml"])
def test_suspicious_chart_root_file_cannot_enter_the_package(tmp_path: Path, name: str) -> None:
    chart = _chart(tmp_path, helmignore="*.tgz\n")
    (chart / name).write_text("secrets:\n  jwtSecret: placeholder-free-content\n", encoding="utf-8")
    findings = package_scan.check_chart_directory(chart)
    reasons = {finding.reason for finding in findings if finding.path == name}
    assert reasons, f"{name} would have been packaged silently"
    assert reasons <= {
        contract.REASON_SECRET_MATERIAL_FILE,
        contract.REASON_UNEXPECTED_CHART_FILE,
        contract.REASON_NOT_PLACEHOLDER,
        contract.REASON_BLOCK_NOT_PLACEHOLDER,
    }


def test_local_values_excluded_by_helmignore_is_accepted(tmp_path: Path) -> None:
    """helm never packages it, so its presence on disk is not a packaging finding."""
    chart = _chart(tmp_path)
    (chart / "values.local.yaml").write_text("secrets:\n  jwtSecret: local-only\n", encoding="utf-8")
    assert package_scan.check_chart_directory(chart) == []


def test_missing_helmignore_is_reported(tmp_path: Path) -> None:
    chart = _chart(tmp_path, helmignore=None)
    reasons = {finding.reason for finding in package_scan.check_chart_directory(chart)}
    assert contract.REASON_MISSING_HELMIGNORE in reasons


def test_helmignore_without_the_local_values_patterns_is_reported(tmp_path: Path) -> None:
    chart = _chart(tmp_path, helmignore="*.tgz\n")
    findings = package_scan.check_chart_directory(chart)
    assert {finding.key for finding in findings if finding.reason == contract.REASON_HELMIGNORE_GAP} == {
        "*.local.yaml",
        "*.local.yml",
    }


def test_untracked_secret_material_in_templates_is_reported(tmp_path: Path) -> None:
    chart = _chart(tmp_path)
    (chart / "templates" / "tls.key").write_text("not-a-real-key\n", encoding="utf-8")
    assert [finding.reason for finding in package_scan.check_chart_directory(chart)] == [
        contract.REASON_SECRET_MATERIAL_FILE
    ]


def test_expected_extra_values_file_can_be_allowed_explicitly(tmp_path: Path) -> None:
    chart = _chart(tmp_path)
    (chart / "values.images.yaml").write_text('images:\n  api:\n    tag: "abc"\n', encoding="utf-8")
    assert package_scan.check_chart_directory(chart) != []
    assert package_scan.check_chart_directory(chart, frozenset({"values.images.yaml"})) == []


def test_allowed_extra_values_file_is_still_scanned_for_material(tmp_path: Path) -> None:
    chart = _chart(tmp_path)
    (chart / "values.images.yaml").write_text(f'secrets:\n  jwtSecret: "{FAKE_MATERIAL}"\n', encoding="utf-8")
    findings = package_scan.check_chart_directory(chart, frozenset({"values.images.yaml"}))
    assert _reasons(findings) == [("jwtSecret", contract.REASON_BLOCK_NOT_PLACEHOLDER)]


def test_chart_values_with_material_fails_the_package_check(tmp_path: Path) -> None:
    values = f'secrets:\n  jwtSecret: "{FAKE_MATERIAL}"\n  adminPassword: "REPLACE_WITH_BASE64_ADMIN_PASSWORD"\n'
    chart = _chart(tmp_path, values=values)
    assert _reasons(package_scan.check_chart_directory(chart)) == [
        ("jwtSecret", contract.REASON_BLOCK_NOT_PLACEHOLDER)
    ]


@pytest.mark.parametrize(
    ("name", "content", "expected_key"),
    [
        ("app.env.example", f"JWT_SECRET={FAKE_MATERIAL}\n", "JWT_SECRET"),
        ("mysecret.yaml.example", SECRET_MANIFEST.format(value=FAKE_MATERIAL), "JWT_SECRET"),
        ("values.override.yaml.template", f'secrets:\n  jwtSecret: "{FAKE_MATERIAL}"\n', "jwtSecret"),
    ],
)
def test_documentation_copy_at_the_chart_root_is_scanned_not_waved_through(
    tmp_path: Path, name: str, content: str, expected_key: str
) -> None:
    """A chart root accepts documentation copies, so their content has to be checked."""
    chart = _chart(tmp_path)
    (chart / name).write_text(content, encoding="utf-8")
    findings = package_scan.check_chart_directory(chart)
    assert [finding.key for finding in findings] == [expected_key], [f.render() for f in findings]


@pytest.mark.parametrize("name", ["tls.key.example", "client.p12.sample", "kubeconfig.template"])
def test_documentation_copy_of_an_uninspectable_file_type_is_still_rejected(tmp_path: Path, name: str) -> None:
    """Nothing inside a keystore can be verified, so the suffix buys it no acceptance."""
    chart = _chart(tmp_path)
    (chart / name).write_text("fixture-content\n", encoding="utf-8")
    assert [finding.reason for finding in package_scan.check_chart_directory(chart)] == [
        contract.REASON_SECRET_MATERIAL_FILE
    ]


def test_sanitized_local_values_example_is_accepted_at_the_chart_root(tmp_path: Path) -> None:
    chart = _chart(tmp_path)
    (chart / "values.local.yaml.example").write_text(
        'secrets:\n  jwtSecret: "REPLACE_WITH_BASE64_JWT_SECRET"\n', encoding="utf-8"
    )
    assert package_scan.check_chart_directory(chart) == []


def test_chart_root_values_missing_a_weak_default_key_fails_the_package_check(tmp_path: Path) -> None:
    chart = _chart(tmp_path, values='secrets:\n  adminPassword: "REPLACE_WITH_BASE64_ADMIN_PASSWORD"\n')
    assert _reasons(package_scan.check_chart_directory(chart)) == [
        ("jwtSecret", contract.REASON_MISSING_WEAK_DEFAULT)
    ]


def test_chart_without_a_values_file_reports_every_weak_default_key(tmp_path: Path) -> None:
    chart = _chart(tmp_path)
    (chart / "values.yaml").unlink()
    assert _reasons(package_scan.check_chart_directory(chart)) == [
        ("adminPassword", contract.REASON_MISSING_WEAK_DEFAULT),
        ("jwtSecret", contract.REASON_MISSING_WEAK_DEFAULT),
    ]


def test_package_checker_cli_reports_without_printing_the_value(tmp_path: Path) -> None:
    chart = _chart(tmp_path, helmignore="*.tgz\n")
    (chart / "values-local.yaml").write_text(f'secrets:\n  jwtSecret: "{FAKE_MATERIAL}"\n', encoding="utf-8")
    result = subprocess.run([sys.executable, str(PACKAGE_CHECKER), str(chart)], capture_output=True, text=True)
    assert result.returncode == 1
    assert "values-local.yaml" in result.stderr
    assert FAKE_MATERIAL not in result.stdout + result.stderr


def test_package_checker_cli_rejects_a_directory_without_a_chart(tmp_path: Path) -> None:
    result = subprocess.run([sys.executable, str(PACKAGE_CHECKER), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 2
