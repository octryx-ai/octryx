"""Secret documents written as one root-level flow mapping.

`{apiVersion: v1, kind: Secret, data: {JWT_SECRET: <material>}}` is a valid Kubernetes Secret
and, without this handling, it produced **zero findings and exit 0** from both preflights. Not a
wrong verdict, an absent one: `looks_like_secret_manifest` recognised only a `kind: Secret`
*line*, and a document that declares every one of its keys inside braces has no such line, so
the manifest was never detected and its data block was never classified. The JSON spelling of
the same document (`{"kind": "Secret", "data": {...}}`) failed the same way.

A second silent pass of the same class is closed here too, and it was already *detected*: a
JSON-style manifest spread over several lines matched the line reader on its indented
`"kind": "Secret",` line, so the document counted as a Secret — and then every one of its
`data` entries sat on an indented line under no block key, so nothing classified them. Zero
findings on a detected Secret. A root flow mapping whose braces do not close on its line is
therefore reported as `secret-document-not-readable` rather than passed.

What is deliberately *not* claimed: no YAML parser was added. `yaml_lines` reads bounded
document shape. Kubernetes `kind: List` block-sequence items are covered by the structural
scanner, but a bare root flow *sequence* (`[{kind: Secret, ...}]`) still has no Kubernetes
document kind to anchor it, and a Helm *values* file written as a root flow mapping is still not
read by `values_scan`.

Every fixture is locally invented text: 32 repeated `a` characters, `changeme`, or a
`REPLACE_WITH_*` placeholder. Assertions compare path, line, key name and reason code only, and
two tests prove that the findings for these forms carry no value at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from secret_containment import contract, env_scan  # noqa: E402

from tests.secret_containment_root_flow_support import FAKE_MATERIAL, _scan  # noqa: E402

PLACEHOLDER = "REPLACE_WITH_BASE64_JWT_SECRET"


# ── the reported bypass: a whole Secret on one line ────────────────────────────


def test_a_secret_written_entirely_as_a_root_flow_mapping_is_detected_and_scanned() -> None:
    """A secret written as one root flow mapping (valid YAML) is detected and scanned, never zero findings and exit
    0."""
    text = f"{{apiVersion: v1, kind: Secret, data: {{JWT_SECRET: {FAKE_MATERIAL}}}}}\n"
    assert env_scan.looks_like_secret_manifest(text)
    assert _scan(text) == [("secrets.yaml", 1, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)]


@pytest.mark.parametrize("block", ["data", "stringData"])
def test_both_secret_block_spellings_are_read_inside_a_root_flow_mapping(block: str) -> None:
    text = f"{{apiVersion: v1, kind: Secret, type: Opaque, {block}: {{JWT_SECRET: {FAKE_MATERIAL}}}}}\n"
    assert _scan(text) == [("secrets.yaml", 1, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)]


@pytest.mark.parametrize("block", ["data", "stringData"])
@pytest.mark.parametrize("comment", ["  # bootstrap credentials", " #no space after the hash", "\t# tabbed"])
def test_a_root_flow_secret_with_a_trailing_comment_is_still_scanned(block: str, comment: str) -> None:
    text = f"{{kind: Secret, {block}: {{JWT_SECRET: {FAKE_MATERIAL}}}}}{comment}\n"
    assert _scan(text) == [("secrets.yaml", 1, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)]


def test_every_entry_of_a_root_flow_secret_block_is_reported_on_its_own() -> None:
    text = f"{{kind: Secret, data: {{JWT_SECRET: {FAKE_MATERIAL}, ADMIN_PASSWORD: changeme}}}}\n"
    assert _scan(text) == [
        ("secrets.yaml", 1, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER),
        ("secrets.yaml", 1, "ADMIN_PASSWORD", contract.REASON_WEAK_VALUE),
    ]


def test_the_json_spelling_of_a_root_flow_secret_is_read_the_same_way() -> None:
    """Quoted keys and quoted scalars: the same document, written as JSON, is valid YAML."""
    text = f'{{"apiVersion": "v1", "kind": "Secret", "data": {{"JWT_SECRET": "{FAKE_MATERIAL}"}}}}\n'
    assert env_scan.looks_like_secret_manifest(text)
    assert _scan(text) == [("secrets.yaml", 1, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)]


def test_a_root_flow_secret_holding_only_placeholders_is_accepted() -> None:
    text = f'{{kind: Secret, data: {{JWT_SECRET: "{PLACEHOLDER}", OPENROUTER_API_KEY: ""}}}}\n'
    assert env_scan.looks_like_secret_manifest(text)
    assert env_scan.scan_secret_manifest("secrets.yaml", text) == []


def test_a_root_flow_secret_whose_block_is_a_template_expression_is_a_reference() -> None:
    """The chart's own spelling, inlined: the renderer resolves it, nothing is stored here."""
    text = "{kind: Secret, data: {{ toYaml .Values.secrets | nindent 2 }}}\n"
    assert env_scan.looks_like_secret_manifest(text)
    assert env_scan.scan_secret_manifest("templates/secrets.yaml", text) == []


@pytest.mark.parametrize("block_value", ["{}", ""])
def test_a_root_flow_secret_with_an_empty_block_reports_nothing(block_value: str) -> None:
    text = f"{{kind: Secret, data: {block_value}}}\n"
    assert env_scan.looks_like_secret_manifest(text)
    assert env_scan.scan_secret_manifest("secrets.yaml", text) == []


def test_only_the_secret_blocks_of_a_root_flow_document_are_classified() -> None:
    """`metadata` and `type` are document structure, not secret material."""
    text = f"{{kind: Secret, metadata: {{name: app-secrets, namespace: octryx}}, data: {{JWT_SECRET: {FAKE_MATERIAL}}}}}\n"
    assert _scan(text) == [("secrets.yaml", 1, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)]


def test_a_root_flow_kind_without_a_space_after_the_colon_still_declares_a_secret() -> None:
    text = f"{{kind:Secret,data:{{JWT_SECRET:{FAKE_MATERIAL}}}}}\n"
    assert env_scan.looks_like_secret_manifest(text)
    assert _scan(text) == [("secrets.yaml", 1, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)]


@pytest.mark.parametrize("quote", ['"', "'"])
def test_a_hash_inside_a_quoted_root_flow_value_is_not_read_as_a_comment(quote: str) -> None:
    """Cutting at the wrong `#` would silently shorten the value that gets classified."""
    text = f"{{kind: Secret, data: {{JWT_SECRET: {quote}{FAKE_MATERIAL} # not a comment{quote}}}}}  # a comment\n"
    assert _scan(text) == [("secrets.yaml", 1, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)]


def test_a_quoted_hash_does_not_turn_a_weak_root_flow_value_into_material() -> None:
    text = '{kind: Secret, stringData: {ADMIN_PASSWORD: "changeme # yes really"}}  # rotate me\n'
    assert _scan(text) == [("secrets.yaml", 1, "ADMIN_PASSWORD", contract.REASON_WEAK_VALUE)]


@pytest.mark.parametrize("kind", ["ConfigMap", "SecretStore", "SealedSecret"])
def test_a_root_flow_document_of_another_kind_is_not_read_as_a_secret(kind: str) -> None:
    text = f"{{apiVersion: v1, kind: {kind}, data: {{JWT_SECRET: {FAKE_MATERIAL}}}}}\n"
    assert not env_scan.looks_like_secret_manifest(text)
    assert env_scan.scan_secret_manifest("other.yaml", text) == []


# ── a root flow document that does not close fails closed ──────────────────────


@pytest.mark.parametrize(
    "line",
    [
        "{kind: Secret, data: {JWT_SECRET: MATERIAL",
        "{kind: Secret, data: {JWT_SECRET: MATERIAL}",
        "{kind: Secret, data: {JWT_SECRET: MATERIAL} # note",
        "{kind: Secret, data: {JWT_SECRET: MATERIAL}}}",
        '{kind: Secret, data: {JWT_SECRET: "MATERIAL}}',
        "{kind: Secret, stringData: {JWT_SECRET: MATERIAL",
    ],
)
def test_a_root_flow_secret_whose_braces_do_not_close_is_reported_not_skipped(line: str) -> None:
    """The fail-closed half. The document continues past what a line reader can see, so it is
    reported as unreadable; claiming it was scanned is what a silent pass looks like."""
    text = f"{line.replace('MATERIAL', FAKE_MATERIAL)}\n"
    assert env_scan.looks_like_secret_manifest(text)
    assert _scan(text) == [("secrets.yaml", 1, "", contract.REASON_DOCUMENT_UNREADABLE)]


def test_a_multi_line_json_secret_manifest_is_reported_instead_of_passing_silently() -> None:
    """This form was *detected* before and still yielded zero findings: the indented
    `"kind": "Secret",` line matched the line reader, and every data entry then sat under no
    block key. The unclosed opening brace is now the finding."""
    text = f'{{\n  "apiVersion": "v1",\n  "kind": "Secret",\n  "data": {{"JWT_SECRET": "{FAKE_MATERIAL}"}}\n}}\n'
    assert env_scan.looks_like_secret_manifest(text)
    assert _scan(text) == [("secrets.yaml", 1, "", contract.REASON_DOCUMENT_UNREADABLE)]


def test_a_multi_line_flow_secret_whose_first_line_already_names_the_kind_is_reported() -> None:
    text = f"{{kind: Secret, data:\n  {{JWT_SECRET: {FAKE_MATERIAL}}}}}\n"
    assert env_scan.looks_like_secret_manifest(text)
    assert _scan(text) == [("secrets.yaml", 1, "", contract.REASON_DOCUMENT_UNREADABLE)]


@pytest.mark.parametrize("block", ["data", "stringData"])
@pytest.mark.parametrize("value", ["MATERIAL", "[MATERIAL]", "|"])
def test_a_closed_root_flow_document_with_an_unreadable_block_reports_that_block(block: str, value: str) -> None:
    """The document reads, the block does not: the finding names the block key, as it does for
    the indented spelling. One classification, reached from either form."""
    text = f"{{kind: Secret, {block}: {value.replace('MATERIAL', FAKE_MATERIAL)}}}\n"
    assert _scan(text) == [("secrets.yaml", 1, block, contract.REASON_BLOCK_UNREADABLE)]


@pytest.mark.parametrize("kind", ["ConfigMap", "ExternalSecret"])
def test_an_unreadable_root_flow_document_of_another_kind_is_not_reported(kind: str) -> None:
    """A recorded bound, not an oversight: a malformed non-Secret document is left to whatever
    validates YAML. Reporting every unbalanced brace in every scanned file is a different rule."""
    text = f"{{kind: {kind}, data: {{JWT_SECRET: {FAKE_MATERIAL}\n"
    assert not env_scan.looks_like_secret_manifest(text)
    assert env_scan.scan_secret_manifest("other.yaml", text) == []


def test_the_unreadable_document_finding_names_no_key_and_no_value() -> None:
    text = f"{{kind: Secret, data: {{JWT_SECRET: {FAKE_MATERIAL}\n"
    (finding,) = env_scan.scan_secret_manifest("secrets.yaml", text)
    assert finding.render() == f"secrets.yaml:1: reason={contract.REASON_DOCUMENT_UNREADABLE}"
    assert FAKE_MATERIAL not in finding.render()
