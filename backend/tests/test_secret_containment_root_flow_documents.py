"""The root flow document reader: indentation, line and block boundaries, later documents, enclosing keys, the recorded sequence and values bounds, and findings without the value."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from secret_containment import contract, env_scan, values_scan, yaml_lines  # noqa: E402

from tests.secret_containment_root_flow_support import FAKE_MATERIAL, _scan  # noqa: E402

# ── boundaries: what is not a root flow document ───────────────────────────────


def test_an_indented_flow_mapping_is_a_value_not_a_document_root() -> None:
    """A document root starts at column 0. Indented, the same text is the value of a key above
    it, and the existing value reader owns it."""
    assert yaml_lines.root_flow_document(f"  {{kind: Secret, data: {{A: {FAKE_MATERIAL}}}}}") is None
    text = f"  {{apiVersion: v1, kind: Secret, data: {{JWT_SECRET: {FAKE_MATERIAL}}}}}\n"
    assert not env_scan.looks_like_secret_manifest(text)


@pytest.mark.parametrize(
    "raw",
    [
        "{{- if .Values.secrets }}",
        "{{ toYaml .Values.secrets | nindent 2 }}",
        "kind: Secret",
        "}",
        "- kind: Secret",
        "",
    ],
)
def test_lines_that_do_not_open_a_root_flow_mapping_are_not_read_as_documents(raw: str) -> None:
    assert yaml_lines.root_flow_document(raw) is None


def test_a_line_form_secret_manifest_is_unaffected_by_the_document_reader() -> None:
    text = f"apiVersion: v1\nkind: Secret\ntype: Opaque\ndata:\n  JWT_SECRET: {FAKE_MATERIAL}\n"
    assert _scan(text) == [("secrets.yaml", 5, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)]


def test_a_root_flow_document_does_not_close_an_open_secret_block() -> None:
    """Deliberately malformed input — a document cannot validly hold both forms. The added
    branch leaves the block state alone, so the enclosing `data` block keeps applying instead of
    being silently closed by a line that is not a block key."""
    text = f"kind: Secret\ndata:\n{{apiVersion: v1, kind: ConfigMap}}\n  JWT_SECRET: {FAKE_MATERIAL}\n"
    assert _scan(text) == [("secrets.yaml", 4, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER)]


def test_a_root_flow_secret_in_the_second_document_is_reported_on_its_own_line() -> None:
    text = (
        "apiVersion: v1\n"
        "kind: Secret\n"
        "data:\n"
        f"  JWT_SECRET: {FAKE_MATERIAL}\n"
        "---\n"
        "{kind: Secret, stringData: {ADMIN_PASSWORD: changeme}}\n"
    )
    assert _scan(text) == [
        ("secrets.yaml", 4, "JWT_SECRET", contract.REASON_NOT_PLACEHOLDER),
        ("secrets.yaml", 6, "ADMIN_PASSWORD", contract.REASON_WEAK_VALUE),
    ]


# ── the document reader's own contract ─────────────────────────────────────────


def test_root_flow_document_keeps_the_enclosing_keys_instead_of_flattening_them() -> None:
    """`flow_mapping_entries` flattens to leaves, which is what a value position needs. At
    document level the enclosing key *is* the information: `kind` says what the document is and
    `data` says which values are material."""
    document = yaml_lines.root_flow_document("{apiVersion: v1, kind: Secret, data: {A: 1, B: 2}}")
    assert document is not None
    assert document.complete
    assert [(entry.key, entry.value) for entry in document.entries] == [
        ("apiVersion", "v1"),
        ("kind", "Secret"),
        ("data", "{A: 1, B: 2}"),
    ]


@pytest.mark.parametrize(
    ("raw", "complete", "keys"),
    [
        ("{}", True, []),
        ("{kind: Secret}", True, ["kind"]),
        ("{kind: Secret}  # note", True, ["kind"]),
        ('{"kind": "Secret"}', True, ["kind"]),
        ("{kind: Secret, data: {A: 1}", False, ["kind", "data"]),
        ("{kind: Secret,", False, ["kind"]),
        ("{", False, []),
        ("{kind: Secret}}", False, ["kind"]),
        ('{kind: "Secret', False, ["kind"]),
    ],
)
def test_root_flow_document_reports_whether_the_line_closes_what_it_opened(
    raw: str, complete: bool, keys: list[str]
) -> None:
    document = yaml_lines.root_flow_document(raw)
    assert document is not None
    assert document.complete is complete
    assert [entry.key for entry in document.entries] == keys


# ── recorded bounds: still line shape, not a YAML parser ───────────────────────


def test_a_root_flow_sequence_of_secrets_is_the_recorded_sequence_bound() -> None:
    """Pins the documented sequence-root boundary rather than
    claiming coverage. `root_flow_document` reads a mapping at the document root; unlike a
    Kubernetes `kind: List`, this bare sequence has no document kind that can anchor a bounded
    fail-closed decision. No tracked file uses the form."""
    text = f"[{{apiVersion: v1, kind: Secret, data: {{JWT_SECRET: {FAKE_MATERIAL}}}}}]\n"
    assert yaml_lines.root_flow_document(text.strip()) is None
    assert not env_scan.looks_like_secret_manifest(text)
    assert env_scan.scan_secret_manifest("list.yaml", text) == []


def test_a_values_file_written_as_a_root_flow_mapping_is_the_recorded_values_bound() -> None:
    """Also documented, also not claimed: `values_scan` tracks the enclosing block through
    indented `key: value` lines, so a values file whose whole content is one flow mapping is not
    read. No tracked values file uses the form; the manifest scanner is the path that a
    generated Secret actually takes."""
    content = f"{{secrets: {{jwtSecret: {FAKE_MATERIAL}, adminPassword: changeme}}}}\n"
    assert values_scan.scan_values_file("values.yaml", content) == []


# ── no value ever reaches the output ───────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        f"{{apiVersion: v1, kind: Secret, data: {{JWT_SECRET: {FAKE_MATERIAL}}}}}\n",
        f"{{kind: Secret, stringData: {{JWT_SECRET: {FAKE_MATERIAL}}}}}  # bootstrap\n",
        f'{{"kind": "Secret", "data": {{"JWT_SECRET": "{FAKE_MATERIAL}"}}}}\n',
        f'{{kind: Secret, data: {{JWT_SECRET: "{FAKE_MATERIAL} # no"}}}}  # yes\n',
        f"{{kind: Secret, data: {FAKE_MATERIAL}}}\n",
        f"{{kind: Secret, data: {{JWT_SECRET: {FAKE_MATERIAL}\n",
        f'{{\n  "kind": "Secret",\n  "data": {{"JWT_SECRET": "{FAKE_MATERIAL}"}}\n}}\n',
    ],
)
def test_findings_for_root_flow_documents_never_contain_the_value(text: str) -> None:
    findings = env_scan.scan_secret_manifest("secrets.yaml", text)
    assert findings
    for finding in findings:
        assert FAKE_MATERIAL not in finding.render()
