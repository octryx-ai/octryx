"""Valid YAML forms the containment scanners must not walk past."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from secret_containment import contract, env_scan, values_scan, yaml_lines  # noqa: E402

from tests.services.secret.secret_containment_yaml_forms_support import (  # noqa: E402
    FAKE_MATERIAL,
    REQUIRED_JWT,
    _findings,
)


@pytest.mark.parametrize(
    "kind_line",
    [
        "kind: Secret  # bootstrap credentials",
        'kind: "Secret" # quoted and commented',
        "kind: 'Secret'",
        "kind : Secret",
        "kind: Secret\t",
    ],
)
def test_secret_kind_is_recognised_whatever_follows_it_on_the_line(kind_line: str) -> None:
    text = f"apiVersion: v1\n{kind_line}\ntype: Opaque\nstringData:\n  JWT_SECRET: {FAKE_MATERIAL}\n"
    assert env_scan.looks_like_secret_manifest(text)
    assert _findings(env_scan.scan_secret_manifest("secret.yaml", text)) == [
        ("secret.yaml", 5, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)
    ]


@pytest.mark.parametrize("kind_line", ["kind: SecretStore", "kind: ConfigMap  # not a Secret", "kind: SealedSecret"])
def test_a_neighbouring_kind_is_not_read_as_a_secret_manifest(kind_line: str) -> None:
    text = f"apiVersion: v1\n{kind_line}\ndata:\n  JWT_SECRET: {FAKE_MATERIAL}\n"
    assert not env_scan.looks_like_secret_manifest(text)
    assert env_scan.scan_secret_manifest("other.yaml", text) == []


def test_inline_data_mapping_is_scanned_entry_by_entry() -> None:
    text = f'apiVersion: v1\nkind: Secret\ndata: {{JWT_SECRET: {FAKE_MATERIAL}, OPENROUTER_API_KEY: ""}}\n'
    assert _findings(env_scan.scan_secret_manifest("secrets.yaml", text)) == [
        ("secrets.yaml", 3, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)
    ]


def test_inline_string_data_mapping_reports_every_entry_that_carries_material() -> None:
    text = f"kind: Secret\nstringData: {{JWT_SECRET: {FAKE_MATERIAL}, ADMIN_PASSWORD: changeme}}\n"
    assert _findings(env_scan.scan_secret_manifest("secrets.yaml", text)) == [
        ("secrets.yaml", 2, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER),
        ("secrets.yaml", 2, "ADMIN_PASSWORD", contract.REASON_WEAK_VALUE),
    ]


def test_a_flow_mapping_as_the_value_of_a_data_entry_is_descended_into() -> None:
    text = f"kind: Secret\ndata:\n  OUTER: {{INNER: {FAKE_MATERIAL}}}\n"
    assert _findings(env_scan.scan_secret_manifest("secrets.yaml", text)) == [
        ("secrets.yaml", 3, "INNER", contract.REASON_NOT_PLACEHOLDER)
    ]


def test_a_template_expression_data_block_is_not_torn_into_entries() -> None:
    text = "kind: Secret\ndata: {{ toYaml .Values.secrets | nindent 2 }}\n"
    assert env_scan.looks_like_secret_manifest(text)
    assert env_scan.scan_secret_manifest("templates/secrets.yaml", text) == []


def test_inline_secret_block_mapping_in_a_values_file_is_scanned() -> None:
    content = f"secrets: {{jwtSecret: {FAKE_MATERIAL}, adminPassword: changeme}}\n"
    assert _findings(values_scan.scan_values_file("values.yaml", content)) == [
        ("values.yaml", 1, "jwtSecret", contract.REASON_BLOCK_NOT_PLACEHOLDER),
        ("values.yaml", 1, "adminPassword", contract.REASON_WEAK_VALUE),
    ]


def test_inline_secret_block_mapping_with_placeholders_satisfies_the_required_keys() -> None:
    content = 'secrets: {jwtSecret: "REPLACE_WITH_BASE64_JWT_SECRET"}\n'
    assert values_scan.scan_values_file("values.yaml", content, REQUIRED_JWT, REQUIRED_JWT) == []


def test_a_flow_mapping_outside_the_secret_block_still_reaches_secret_material_keys() -> None:
    content = f"config: {{jwtSecret: {FAKE_MATERIAL}}}\n"
    assert _findings(values_scan.scan_values_file("values.yaml", content)) == [
        ("values.yaml", 1, "jwtSecret", contract.REASON_NOT_PLACEHOLDER)
    ]


@pytest.mark.parametrize("block", ["data", "stringData"])
@pytest.mark.parametrize("comment", ["  # bootstrap credentials", " #no space after the hash", "\t# tabbed"])
def test_an_inline_data_mapping_with_a_trailing_comment_is_still_scanned(block: str, comment: str) -> None:
    text = f"kind: Secret\n{block}: {{JWT_SECRET: {FAKE_MATERIAL}}}{comment}\n"
    assert _findings(env_scan.scan_secret_manifest("secrets.yaml", text)) == [
        ("secrets.yaml", 2, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)
    ]


@pytest.mark.parametrize("block", ["data", "stringData"])
def test_a_commented_inline_mapping_reports_every_entry_it_declares(block: str) -> None:
    text = f"kind: Secret\n{block}: {{JWT_SECRET: {FAKE_MATERIAL}, ADMIN_PASSWORD: changeme}}  # both\n"
    assert _findings(env_scan.scan_secret_manifest("secrets.yaml", text)) == [
        ("secrets.yaml", 2, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER),
        ("secrets.yaml", 2, "ADMIN_PASSWORD", contract.REASON_WEAK_VALUE),
    ]


def test_a_trailing_comment_on_an_empty_data_block_leaves_the_indented_entries_readable() -> None:
    text = f"kind: Secret\ndata:  # entries below\n  JWT_SECRET: {FAKE_MATERIAL}\n"
    assert _findings(env_scan.scan_secret_manifest("secrets.yaml", text)) == [
        ("secrets.yaml", 3, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)
    ]


def test_a_template_data_block_with_a_trailing_comment_is_still_a_reference() -> None:
    text = "kind: Secret\ndata: {{ toYaml .Values.secrets | nindent 2 }}  # rendered by Helm\n"
    assert env_scan.scan_secret_manifest("templates/secrets.yaml", text) == []


def test_an_inline_secret_block_with_a_trailing_comment_is_scanned_in_a_values_file() -> None:
    content = f"secrets: {{jwtSecret: {FAKE_MATERIAL}, adminPassword: changeme}}  # local overrides\n"
    assert _findings(values_scan.scan_values_file("values.yaml", content)) == [
        ("values.yaml", 1, "jwtSecret", contract.REASON_BLOCK_NOT_PLACEHOLDER),
        ("values.yaml", 1, "adminPassword", contract.REASON_WEAK_VALUE),
    ]


def test_a_commented_flow_mapping_outside_the_secret_block_still_reaches_the_secret_key() -> None:
    content = f"config: {{jwtSecret: {FAKE_MATERIAL}}}  # inline config\n"
    assert _findings(values_scan.scan_values_file("values.yaml", content)) == [
        ("values.yaml", 1, "jwtSecret", contract.REASON_NOT_PLACEHOLDER)
    ]


@pytest.mark.parametrize("block", ["data", "stringData"])
@pytest.mark.parametrize("quote", ['"', "'"])
def test_a_hash_inside_a_quoted_value_is_not_read_as_a_comment(block: str, quote: str) -> None:
    text = f"kind: Secret\n{block}: {{JWT_SECRET: {quote}{FAKE_MATERIAL} # not a comment{quote}}}  # a comment\n"
    assert _findings(env_scan.scan_secret_manifest("secrets.yaml", text)) == [
        ("secrets.yaml", 2, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)
    ]


def test_a_quoted_hash_does_not_turn_a_weak_value_into_material() -> None:
    text = 'kind: Secret\ndata: {ADMIN_PASSWORD: "changeme # yes really"}  # rotate me\n'
    assert _findings(env_scan.scan_secret_manifest("secrets.yaml", text)) == [
        ("secrets.yaml", 2, "ADMIN_PASSWORD", contract.REASON_WEAK_VALUE)
    ]


def test_a_quoted_hash_in_a_values_secret_block_keeps_the_placeholder_intact() -> None:
    content = 'secrets: {jwtSecret: "REPLACE_WITH_BASE64_JWT_SECRET"}  # set per environment\n'
    assert values_scan.scan_values_file("values.yaml", content, REQUIRED_JWT, REQUIRED_JWT) == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("{A: 1} # trailing", "{A: 1}"),
        ("{A: 1}\t#trailing", "{A: 1}"),
        ('{A: "# not a comment"} # yes', '{A: "# not a comment"}'),
        ("{A: '#'}", "{A: '#'}"),
        ("# whole line", ""),
        ("no-comment-here", "no-comment-here"),
        ("value#notacomment", "value#notacomment"),
        ("{A: 1 # inside the braces", "{A: 1 # inside the braces"),
    ],
)
def test_strip_trailing_comment_cuts_only_where_yaml_starts_a_comment(value: str, expected: str) -> None:
    assert yaml_lines.strip_trailing_comment(value) == expected
