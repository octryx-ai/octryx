"""Env templates, secret manifests and documentation copies are scanned by content and deployment-tree scope."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from secret_containment import contract, env_scan, file_kinds, tracked_scan  # noqa: E402

from tests.secret_containment_contract_support import (  # noqa: E402
    FAKE_MATERIAL,
    SECRET_MANIFEST,
    TEMPLATE_WITH_WEAK_DEFAULTS,
    _reasons,
)

# ── env templates and Secret manifests ─────────────────────────────────────────


def test_env_template_secret_key_with_material_is_reported() -> None:
    content = f"# template\nPOSTGRES_PASSWORD={FAKE_MATERIAL}\nLOG_LEVEL=debug\n"
    assert _reasons(env_scan.scan_env_file("secret-template.env", content)) == [
        ("POSTGRES_PASSWORD", contract.REASON_NOT_PLACEHOLDER)
    ]


def test_env_template_weak_value_is_reported() -> None:
    content = "JWT_SECRET=changeme\n"
    assert _reasons(env_scan.scan_env_file("secret-template.env", content)) == [
        ("JWT_SECRET", contract.REASON_WEAK_VALUE)
    ]


def test_env_template_placeholders_and_empty_values_pass() -> None:
    content = (
        "POSTGRES_PASSWORD=REPLACE_WITH_POSTGRES_PASSWORD\n"
        "DATABASE_URL=${DATABASE_URL}\n"
        "OPENROUTER_API_KEY=\n"
        "ADMIN_EMAIL=admin@example.com\n"
    )
    assert env_scan.scan_env_file("secret-template.env", content) == []


def test_env_key_suffix_rules_cover_unlisted_secret_names() -> None:
    content = f"GITHUB_TOKEN={FAKE_MATERIAL}\nSERVICE_ENDPOINT=https://example.invalid\n"
    assert _reasons(env_scan.scan_env_file("extra.env", content)) == [
        ("GITHUB_TOKEN", contract.REASON_NOT_PLACEHOLDER)
    ]


@pytest.mark.parametrize(
    "key",
    ["AWS_SECRET_ACCESS_KEY", "TOKEN_SECRET_KEY", "OCTRYX_KNOWLEDGE_FEDERATION_SIGNING_KEY"],
)
def test_secret_env_suffixes_cover_names_this_repository_actually_uses(key: str) -> None:
    assert contract.is_secret_env_key(key)


@pytest.mark.parametrize("key", ["AWS_ACCESS_KEY_ID", "AWS_DEFAULT_REGION", "COMPAT_PASS", "DIM_RESULT_PASS"])
def test_non_secret_env_names_stay_out_of_the_suffix_rules(key: str) -> None:
    """The broad ``_KEY`` / ``_PASS`` families are excluded because these names exist here."""
    assert not contract.is_secret_env_key(key)


def test_secret_manifest_entry_with_material_is_reported() -> None:
    findings = env_scan.scan_secret_manifest("secrets.env", SECRET_MANIFEST.format(value=FAKE_MATERIAL))
    assert _reasons(findings) == [("JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)]


def test_secret_manifest_is_detected_by_content_not_by_file_name() -> None:
    text = SECRET_MANIFEST.format(value="changeme")
    assert env_scan.looks_like_secret_manifest(text)
    assert _reasons(env_scan.scan_secret_manifest("overlays/eks/secrets.env", text)) == [
        ("JWT_SECRET", contract.REASON_WEAK_VALUE)
    ]


def test_secret_manifest_entries_are_secret_by_contract_even_for_unlisted_keys() -> None:
    text = SECRET_MANIFEST.replace("JWT_SECRET", "SOME_OTHER_ENTRY").format(value=FAKE_MATERIAL)
    assert _reasons(env_scan.scan_secret_manifest("secrets.yaml", text)) == [
        ("SOME_OTHER_ENTRY", contract.REASON_NOT_PLACEHOLDER)
    ]


def test_helm_secret_template_with_template_references_passes() -> None:
    assert env_scan.scan_secret_manifest("templates/secrets.yaml", TEMPLATE_WITH_WEAK_DEFAULTS) == []


def test_non_secret_manifest_metadata_is_not_scanned() -> None:
    text = "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: fixture\ndata:\n  JWT_SECRET: not-a-secret-manifest\n"
    assert env_scan.scan_secret_manifest("configmap.yaml", text) == []


# ── documentation copies ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("values.yaml", "values.yaml"),
        ("values.yaml.example", "values.yaml"),
        ("values.local.yaml.example", "values.local.yaml"),
        ("app.env.template", "app.env"),
        ("mysecret.YAML.Example", "mysecret.YAML"),
        ("secrets.env.example.template", "secrets.env"),
        ("README.md", "README.md"),
        (".example", ".example"),
    ],
)
def test_effective_name_strips_documentation_suffixes(name: str, expected: str) -> None:
    assert file_kinds.effective_name(name) == expected


@pytest.mark.parametrize(
    "name",
    ["app.env.example", "app.env.sample", "app.env.template", "secret-template.env.example", ".env.example"],
)
def test_documentation_env_copies_are_recognised_as_env_files(name: str) -> None:
    assert file_kinds.is_env_file(name)


@pytest.mark.parametrize("name", ["values.yaml.example", "values.eks.yml.template", "values.local.yaml.example"])
def test_documentation_values_copies_are_recognised_as_values_files(name: str) -> None:
    assert file_kinds.is_values_file(name)


# ── tracked-tree dispatch ──────────────────────────────────────────────────────


def test_tracked_local_values_file_is_reported(tmp_path: Path) -> None:
    (tmp_path / "values.local.yaml").write_text('secrets:\n  jwtSecret: ""\n', encoding="utf-8")
    assert [finding.reason for finding in tracked_scan.check_paths(tmp_path, ["values.local.yaml"])] == [
        contract.REASON_TRACKED_LOCAL_FILE
    ]


def test_env_template_inside_a_deployment_tree_is_scanned(tmp_path: Path) -> None:
    relative = "deploy/kubernetes/base/secret-template.env"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(f"JWT_SECRET={FAKE_MATERIAL}\n", encoding="utf-8")
    assert _reasons(tracked_scan.check_paths(tmp_path, [relative])) == [
        ("JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)
    ]


@pytest.mark.parametrize("name", ["app.env.example", "app.env.sample", "app.env.template"])
def test_documentation_env_copy_in_a_deployment_tree_is_scanned(tmp_path: Path, name: str) -> None:
    """The suffix says "not the deployed copy"; it does not make the content inert."""
    relative = f"deploy/kubernetes/base/{name}"
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"JWT_SECRET={FAKE_MATERIAL}\n", encoding="utf-8")
    assert _reasons(tracked_scan.check_paths(tmp_path, [relative])) == [
        ("JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)
    ]


@pytest.mark.parametrize("name", ["mysecret.yaml.example", "mysecret.yml.template", "opaque.yaml.sample"])
def test_documentation_secret_manifest_copy_in_a_deployment_tree_is_scanned(tmp_path: Path, name: str) -> None:
    relative = f"deploy/kubernetes/base/{name}"
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SECRET_MANIFEST.format(value=FAKE_MATERIAL), encoding="utf-8")
    assert _reasons(tracked_scan.check_paths(tmp_path, [relative])) == [
        ("JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)
    ]


@pytest.mark.parametrize("name", ["values.yaml.template", "values.yaml.example", "values.eks.yml.sample"])
def test_documentation_values_copy_is_scanned(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_text(f'secrets:\n  jwtSecret: "{FAKE_MATERIAL}"\n', encoding="utf-8")
    assert _reasons(tracked_scan.check_paths(tmp_path, [name])) == [
        ("jwtSecret", contract.REASON_BLOCK_NOT_PLACEHOLDER)
    ]


def test_example_copy_of_a_local_values_file_is_not_treated_as_the_tracked_original(tmp_path: Path) -> None:
    """The sanitized example is the guard that replaces the untracked file, not a leak."""
    relative = "deploy/helm/octryx/values.local.yaml.example"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text('secrets:\n  jwtSecret: "REPLACE_WITH_BASE64_JWT_SECRET"\n', encoding="utf-8")
    assert tracked_scan.check_paths(tmp_path, [relative]) == []


def test_env_file_outside_a_deployment_tree_is_out_of_scope(tmp_path: Path) -> None:
    """Application-level local dev files are a separate concern, documented as such."""
    (tmp_path / ".env.example").write_text(f"JWT_SECRET={FAKE_MATERIAL}\n", encoding="utf-8")
    assert tracked_scan.check_paths(tmp_path, [".env.example"]) == []
