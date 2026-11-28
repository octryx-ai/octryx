"""Unreadable secret blocks are reported instead of skipped, sequence-item and quoted-key secrets are detected, the line helpers read keys and flow mappings, and findings never contain the value."""

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


@pytest.mark.parametrize("block", ["data", "stringData"])
@pytest.mark.parametrize(
    "value",
    [
        "{JWT_SECRET: MATERIAL",
        "{JWT_SECRET: MATERIAL  # never closed",
        "MATERIAL",
        "|",
        "[MATERIAL]",
    ],
)
def test_a_non_empty_unreadable_secret_block_is_reported_instead_of_skipped(block: str, value: str) -> None:
    text = f"kind: Secret\n{block}: {value.replace('MATERIAL', FAKE_MATERIAL)}\n"
    assert _findings(env_scan.scan_secret_manifest("secrets.yaml", text)) == [
        ("secrets.yaml", 2, block, contract.REASON_BLOCK_UNREADABLE)
    ]


@pytest.mark.parametrize("block", ["data", "stringData"])
@pytest.mark.parametrize("value", ["", "  ", "  # entries follow", "{}", "{}  # none yet"])
def test_a_secret_block_that_carries_nothing_on_its_own_line_is_not_reported(block: str, value: str) -> None:
    text = f"kind: Secret\n{block}:{value}\n"
    assert env_scan.scan_secret_manifest("secrets.yaml", text) == []


def test_a_surplus_closing_brace_reports_the_entry_rather_than_the_block() -> None:
    text = f"kind: Secret\ndata: {{JWT_SECRET: {FAKE_MATERIAL}}}}}\n"
    assert _findings(env_scan.scan_secret_manifest("secrets.yaml", text)) == [
        ("secrets.yaml", 2, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)
    ]


def test_an_unreadable_secret_block_finding_names_the_block_and_no_value() -> None:
    text = f"kind: Secret\ndata: {{JWT_SECRET: {FAKE_MATERIAL}\n"
    (finding,) = env_scan.scan_secret_manifest("secrets.yaml", text)
    assert finding.render() == f"secrets.yaml:2: key=data reason={contract.REASON_BLOCK_UNREADABLE}"
    assert FAKE_MATERIAL not in finding.render()


def test_a_malformed_inline_secret_block_in_a_values_file_is_reported_against_the_block() -> None:
    content = f"secrets: {{jwtSecret: {FAKE_MATERIAL}\n"
    assert _findings(values_scan.scan_values_file("values.yaml", content)) == [
        ("values.yaml", 1, "secrets", contract.REASON_BLOCK_NOT_PLACEHOLDER)
    ]


def test_a_secret_written_as_a_sequence_item_is_detected_and_scanned() -> None:
    text = f"kind: List\nitems:\n  - kind: Secret\n    data:\n      JWT_SECRET: {FAKE_MATERIAL}\n"
    assert yaml_lines.match_key_line("  - kind: Secret") is None
    assert yaml_lines.sequence_item("  - kind: Secret") is not None
    assert env_scan.looks_like_secret_manifest(text)
    assert _findings(env_scan.scan_secret_manifest("list.yaml", text)) == [
        ("list.yaml", 5, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)
    ]


@pytest.mark.parametrize("key", ['"openRouterApiKey"', "'openRouterApiKey'"])
def test_quoted_secret_key_in_the_secret_block_is_reported(key: str) -> None:
    content = f"secrets:\n  {key}: {FAKE_MATERIAL}\n"
    assert _findings(values_scan.scan_values_file("values.yaml", content)) == [
        ("values.yaml", 2, "openRouterApiKey", contract.REASON_BLOCK_NOT_PLACEHOLDER)
    ]


def test_quoted_secret_key_holding_a_placeholder_counts_as_declared() -> None:
    content = 'secrets:\n  "jwtSecret": "REPLACE_WITH_BASE64_JWT_SECRET"\n'
    assert values_scan.scan_values_file("values.yaml", content, REQUIRED_JWT, REQUIRED_JWT) == []


def test_quoted_block_key_still_opens_the_secret_block() -> None:
    content = f'"secrets":\n  jwtSecret: {FAKE_MATERIAL}\n'
    assert _findings(values_scan.scan_values_file("values.yaml", content)) == [
        ("values.yaml", 2, "jwtSecret", contract.REASON_BLOCK_NOT_PLACEHOLDER)
    ]


def test_quoted_secret_env_key_in_a_secret_manifest_is_reported() -> None:
    text = f'kind: Secret\nstringData:\n  "JWT_SECRET": {FAKE_MATERIAL}\n'
    assert _findings(env_scan.scan_secret_manifest("secrets.yaml", text)) == [
        ("secrets.yaml", 3, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)
    ]


@pytest.mark.parametrize(
    ("raw", "expected_key"),
    [
        ("  jwtSecret: x", "jwtSecret"),
        ('  "jwtSecret": x', "jwtSecret"),
        ("  'jwtSecret' : x", "jwtSecret"),
        ("kind: Secret", "kind"),
    ],
)
def test_match_key_line_reports_the_key_without_its_quotes(raw: str, expected_key: str) -> None:
    line = yaml_lines.match_key_line(raw)
    assert line is not None
    assert line.key == expected_key


@pytest.mark.parametrize("raw", ["# a comment", "- a list item", "", "no colon here"])
def test_match_key_line_rejects_lines_that_are_not_mapping_entries(raw: str) -> None:
    assert yaml_lines.match_key_line(raw) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("{A: 1, B: 2}", [("A", "1"), ("B", "2")]),
        ('{"A": 1}', [("A", "1")]),
        ("{A: {B: 1}}", [("B", "1")]),
        ("{}", []),
    ],
)
def test_flow_mapping_entries_reads_the_keys_a_one_line_mapping_declares(
    value: str, expected: list[tuple[str, str]]
) -> None:
    entries = yaml_lines.flow_mapping_entries(value)
    assert entries is not None
    assert [(entry.key, entry.value) for entry in entries] == expected


@pytest.mark.parametrize("value", ["plain-scalar", "[1, 2]", "{{ toYaml .Values.secrets }}", ""])
def test_flow_mapping_entries_returns_none_for_values_that_are_not_flow_mappings(value: str) -> None:
    assert yaml_lines.flow_mapping_entries(value) is None


@pytest.mark.parametrize(
    ("scan", "path", "text"),
    [
        (env_scan.scan_secret_manifest, "secrets.yaml", f"kind: Secret # c\ndata:\n  JWT_SECRET: {FAKE_MATERIAL}\n"),
        (env_scan.scan_secret_manifest, "secrets.yaml", f"kind: Secret\ndata: {{JWT_SECRET: {FAKE_MATERIAL}}}\n"),
        (values_scan.scan_values_file, "values.yaml", f'secrets:\n  "jwtSecret": {FAKE_MATERIAL}\n'),
        (values_scan.scan_values_file, "values.yaml", f"secrets: {{jwtSecret: {FAKE_MATERIAL}}}\n"),
        (env_scan.scan_secret_manifest, "secrets.yaml", f"kind: Secret\ndata: {{JWT_SECRET: {FAKE_MATERIAL}}} # c\n"),
        (env_scan.scan_secret_manifest, "secrets.yaml", f"kind: Secret\nstringData: {{K: {FAKE_MATERIAL}}} # c\n"),
        (env_scan.scan_secret_manifest, "secrets.yaml", f"kind: Secret\ndata: {{JWT_SECRET: {FAKE_MATERIAL}\n"),
        (env_scan.scan_secret_manifest, "secrets.yaml", f"kind: Secret\ndata: {FAKE_MATERIAL}\n"),
        (values_scan.scan_values_file, "values.yaml", f"config: {{jwtSecret: {FAKE_MATERIAL}}}  # c\n"),
    ],
)
def test_findings_for_the_newly_covered_forms_never_contain_the_value(scan, path: str, text: str) -> None:
    findings = scan(path, text)
    assert findings
    for finding in findings:
        assert FAKE_MATERIAL not in finding.render()
