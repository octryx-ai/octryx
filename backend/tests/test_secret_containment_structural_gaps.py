"""Fail-closed YAML structures the containment gate must not skip.

The containment gate is deliberately stdlib-only, so it does not pretend to be a
complete YAML parser. These tests pin the safe answer at three structure
boundaries: scalar continuations, explicit/merge mapping keys, and Kubernetes
``kind: List`` sequence items.

All values are invented. Findings expose only path, line, schema key and a fixed
reason; no assertion or diagnostic includes the fixture value.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from secret_containment import contract, env_scan, file_kinds, values_scan, yaml_lines  # noqa: E402

FAKE_MATERIAL = "a" * 32
PLACEHOLDER = "REPLACE_WITH_BASE64_JWT_SECRET"


def _findings(text: str) -> list[tuple[int, str, str]]:
    return [
        (finding.line, finding.key, finding.reason) for finding in env_scan.scan_secret_manifest("probe.yaml", text)
    ]


def test_material_starting_on_a_scalar_continuation_fails_closed() -> None:
    text = f"kind: Secret\ndata:\n  JWT_SECRET:\n    {FAKE_MATERIAL}\n"

    assert _findings(text) == [(4, "JWT_SECRET", contract.REASON_BLOCK_UNREADABLE)]


def test_a_safe_looking_first_scalar_line_cannot_hide_a_material_continuation() -> None:
    text = f"kind: Secret\nstringData:\n  JWT_SECRET: {PLACEHOLDER}\n    {FAKE_MATERIAL}\n"

    assert _findings(text) == [(4, "JWT_SECRET", contract.REASON_BLOCK_UNREADABLE)]


def test_an_already_refused_block_scalar_is_not_reported_twice() -> None:
    text = "kind: Secret\ndata:\n  JWT_SECRET: |\n    invented continuation\n"

    assert _findings(text) == [(3, "JWT_SECRET", contract.REASON_BLOCK_SCALAR)]


@pytest.mark.parametrize(
    "entries",
    [
        f"  ? JWT_SECRET\n  : {FAKE_MATERIAL}",
        f"  ? [JWT_SECRET, alternate]\n  : {FAKE_MATERIAL}",
        "  <<: *secret_defaults",
    ],
)
def test_explicit_and_merge_mapping_syntax_cannot_pass_a_secret_block(entries: str) -> None:
    text = f"kind: Secret\ndata:\n{entries}\n"

    findings = env_scan.scan_secret_manifest("probe.yaml", text)
    assert findings
    assert findings[0].reason == contract.REASON_BLOCK_UNREADABLE
    assert all(FAKE_MATERIAL not in finding.render() for finding in findings)


def test_a_flow_style_merge_key_is_classified_instead_of_skipped() -> None:
    text = "kind: Secret\ndata: {<<: *secret_defaults}\n"

    assert _findings(text) == [(2, "<<", contract.REASON_NOT_PLACEHOLDER)]


@pytest.mark.parametrize(
    "body",
    [
        f"  jwtSecret:\n    {FAKE_MATERIAL}",
        f"  jwtSecret: {PLACEHOLDER}\n    {FAKE_MATERIAL}",
        f"  ? jwtSecret\n  : {FAKE_MATERIAL}",
        "  <<: *secret_defaults",
    ],
)
def test_values_secret_blocks_fail_closed_on_the_same_unreadable_forms(body: str) -> None:
    findings = values_scan.scan_values_file("values.yaml", f"secrets:\n{body}\n")

    assert findings
    assert findings[0].reason == contract.REASON_BLOCK_UNREADABLE
    assert all(FAKE_MATERIAL not in finding.render() for finding in findings)


def test_a_kind_list_secret_item_is_scanned() -> None:
    text = f"kind: List\nitems:\n  - kind: Secret\n    data:\n      JWT_SECRET: {FAKE_MATERIAL}\n"

    assert env_scan.looks_like_secret_manifest(text)
    assert _findings(text) == [(5, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)]


def test_a_list_item_may_declare_kind_after_another_root_field() -> None:
    text = (
        "apiVersion: v1\n"
        "kind: List\n"
        "items:\n"
        "  - apiVersion: v1\n"
        "    kind: Secret\n"
        "    data:\n"
        f"      JWT_SECRET: {FAKE_MATERIAL}\n"
    )

    assert _findings(text) == [(7, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)]


def test_a_secret_after_a_non_secret_list_item_is_not_lost() -> None:
    text = (
        "kind: List\n"
        "items:\n"
        "  - kind: ConfigMap\n"
        "    data:\n"
        "      harmless: value\n"
        "  - kind: Secret\n"
        "    stringData:\n"
        "      JWT_SECRET: changeme\n"
    )

    assert _findings(text) == [(8, "JWT_SECRET", contract.REASON_WEAK_VALUE)]


def test_a_flow_mapping_secret_item_in_a_list_is_scanned() -> None:
    text = f"kind: List\nitems:\n  - {{kind: Secret, data: {{JWT_SECRET: {FAKE_MATERIAL}}}}}\n"

    assert _findings(text) == [(3, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)]


@pytest.mark.parametrize(
    "text",
    [
        f"kind: List\nitems: [{{kind: Secret, data: {{JWT_SECRET: {FAKE_MATERIAL}}}}}]\n",
        f"{{kind: List, items: [{{kind: Secret, data: {{JWT_SECRET: {FAKE_MATERIAL}}}}}]}}\n",
    ],
)
def test_an_unreadable_flow_style_list_fails_closed(text: str) -> None:
    findings = env_scan.scan_secret_manifest("probe.yaml", text)
    assert findings
    assert findings[0].reason == contract.REASON_DOCUMENT_UNREADABLE
    assert FAKE_MATERIAL not in findings[0].render()


def test_an_empty_kubernetes_list_remains_valid() -> None:
    text = "apiVersion: v1\nkind: List\nitems: []\n"

    assert env_scan.looks_like_secret_manifest(text)
    assert env_scan.scan_secret_manifest("probe.yaml", text) == []


def test_kind_list_detection_cannot_disable_the_env_scanner(tmp_path: Path) -> None:
    path = tmp_path / "deployment.env"
    path.write_text(f"kind: List\nJWT_SECRET={FAKE_MATERIAL}\n")

    findings = file_kinds.scan_env_or_secret_path("deployment.env", path)
    assert [(finding.key, finding.reason) for finding in findings] == [("JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)]
    assert FAKE_MATERIAL not in findings[0].render()


def test_a_nested_metadata_sequence_does_not_close_the_outer_secret() -> None:
    text = (
        "kind: Secret\n"
        "metadata:\n"
        "  ownerReferences:\n"
        "    - apiVersion: v1\n"
        "      kind: Deployment\n"
        "data:\n"
        f"  JWT_SECRET: {FAKE_MATERIAL}\n"
    )

    assert _findings(text) == [(7, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)]


def test_sequence_item_detection_never_mistakes_a_document_marker_for_an_item() -> None:
    assert yaml_lines.sequence_item("---") is None
    assert yaml_lines.sequence_item("-1") is None
    item = yaml_lines.sequence_item("  - kind: Secret")
    assert item is not None
    assert (item.indent, item.content) == ("  ", "kind: Secret")


@pytest.mark.parametrize("prefix", ["!!str ", "!<tag:yaml.org,2002:str> ", "&kind "])
def test_tagged_or_anchored_secret_kind_is_still_scanned(prefix: str) -> None:
    text = f"apiVersion: v1\nkind: {prefix}Secret\ndata:\n  JWT_SECRET: {FAKE_MATERIAL}\n"

    assert env_scan.looks_like_secret_manifest(text)
    assert _findings(text) == [(4, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)]


@pytest.mark.parametrize(
    "text",
    [
        f"kindValue: &kind Secret\nkind: *kind\ndata:\n  JWT_SECRET: {FAKE_MATERIAL}\n",
        f"? kind\n: Secret\ndata:\n  JWT_SECRET: {FAKE_MATERIAL}\n",
        f"defaults: &meta {{kind: Secret}}\n<<: *meta\ndata:\n  JWT_SECRET: {FAKE_MATERIAL}\n",
    ],
)
def test_indirect_root_kind_fails_closed_without_exposing_values(text: str) -> None:
    findings = env_scan.scan_secret_manifest("probe.yaml", text)

    assert findings
    assert findings[0].reason == contract.REASON_DOCUMENT_UNREADABLE
    assert all(FAKE_MATERIAL not in finding.render() for finding in findings)


def test_a_similarly_prefixed_explicit_key_is_not_mistaken_for_kind() -> None:
    text = "? kindness\n: harmless\ndata:\n  harmless: value\n"

    assert not env_scan.looks_like_secret_manifest(text)


def test_a_tagged_secret_kind_inside_a_list_is_scanned() -> None:
    text = (
        "kind: List\nitems:\n  - kind: !!str Secret\n    data:\n"
        f"      JWT_SECRET: {FAKE_MATERIAL}\n"
    )

    assert _findings(text) == [(5, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)]


def test_a_merged_list_item_kind_fails_closed() -> None:
    text = (
        "kind: List\nitems:\n  - <<: *secret_meta\n    data:\n"
        f"      JWT_SECRET: {FAKE_MATERIAL}\n"
    )

    findings = env_scan.scan_secret_manifest("probe.yaml", text)
    assert findings
    assert findings[0].reason == contract.REASON_DOCUMENT_UNREADABLE
    assert all(FAKE_MATERIAL not in finding.render() for finding in findings)
