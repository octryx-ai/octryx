"""The Agent Skills format, the bundle manifest/digest and the platform extension (pure)."""

from __future__ import annotations

import pytest

from app.services.skill_catalog import bundle, extension, spec
from app.services.skill_catalog.bundle import BundleError, BundleFile

SKILL_MD = """---
name: terraform-style-guide
description: Generate Terraform HCL code following style conventions. Use when writing Terraform.
allowed-tools: Bash(terraform apply *)
hooks:
  PreToolUse: []
metadata:
  lifecycle-status: active
---

# Terraform Style Guide

## Code Review Checklist

- [ ] Code formatted with `terraform fmt`
"""


def test_parse_and_render_round_trip_keeps_the_body_byte_for_byte():
    parsed = spec.parse_skill_md(SKILL_MD)
    assert parsed.frontmatter["name"] == "terraform-style-guide"
    assert parsed.body.startswith("\n# Terraform Style Guide")
    rendered = spec.render_skill_md(parsed.frontmatter, parsed.body)
    assert spec.parse_skill_md(rendered).body == parsed.body
    assert spec.parse_skill_md(rendered).frontmatter == parsed.frontmatter
    # Unchanged frontmatter keeps the original text exactly.
    assert spec.replace_frontmatter(SKILL_MD, parsed.frontmatter) == SKILL_MD
    changed = spec.replace_frontmatter(SKILL_MD, {**parsed.frontmatter, "description": "Other."})
    assert spec.parse_skill_md(changed).body == parsed.body and "description: Other." in changed


@pytest.mark.parametrize(("text", "code"), [
    ("# no frontmatter", "skill_frontmatter_missing"),
    ("---\nname: [unclosed\n---\nbody", "skill_frontmatter_invalid"),
    ("---\n- a list\n---\nbody", "skill_frontmatter_invalid"),
])
def test_unreadable_skill_md_is_refused_with_a_fixed_code(text, code):
    with pytest.raises(spec.SkillSpecError) as caught:
        spec.parse_skill_md(text)
    assert caught.value.code == code


@pytest.mark.parametrize(("name", "code"), [
    ("", "skill_name_missing"),
    ("a" * 65, "skill_name_too_long"),
    ("Upper", "skill_name_invalid"),
    ("-lead", "skill_name_invalid"),
    ("trail-", "skill_name_invalid"),
    ("dou--ble", "skill_name_invalid"),
    ("under_score", "skill_name_invalid"),
])
def test_names_outside_the_spec_are_refused(name, code):
    assert spec.name_issue(name).code == code


def test_valid_names_pass():
    for name in ("a", "a" * 64, "helm-chart-scaffolding", "x1-2y"):
        assert spec.name_issue(name) is None


def test_validate_skill_reports_every_spec_rule():
    long_md = "\n".join(["line"] * 501)
    issues = spec.validate_skill(
        {"name": "other", "description": "x" * 1025, "compatibility": "y" * 501, "metadata": {"a": 1},
         "license": 3, "when_to_use": "z" * 1025},
        "  ", folder_name="folder", skill_md_text=long_md, paths=["SKILL.md", "references/deep/x.md"])
    codes = {issue.code: issue.severity for issue in issues}
    assert codes == {
        "skill_name_folder_mismatch": "error", "skill_description_too_long": "error",
        "skill_compatibility_invalid": "error", "skill_metadata_invalid": "error", "skill_license_invalid": "error",
        "skill_when_to_use_invalid": "error", "skill_body_empty": "error", "skill_md_long": "warning",
        "skill_reference_too_deep": "warning",
    }
    assert {issue.code for issue in spec.validate_skill(
        {"name": "folder"}, "body", folder_name="folder", skill_md_text="x", paths=[])} == {"skill_description_missing"}
    assert spec.validate_skill({"name": "folder", "description": "d" * 1024}, "body", folder_name="folder",
                               skill_md_text="x\n" * 499, paths=["references/a.md"]) == []


def test_delivery_frontmatter_keeps_only_the_allowlist_and_adds_catalog_metadata():
    parsed = spec.parse_skill_md(SKILL_MD)
    delivered = spec.delivery_frontmatter({**parsed.frontmatter, "model": "x", "when_to_use": "w"},
                                          {"octryx-skill-id": "s1"})
    assert set(delivered) == {"name", "description", "when_to_use", "metadata"}
    assert delivered["metadata"] == {"lifecycle-status": "active", "octryx-skill-id": "s1"}
    assert spec.stripped_keys({**parsed.frontmatter, "model": "x"}) == ["allowed-tools", "hooks", "model"]
    assert set(spec.EXECUTION_FRONTMATTER_KEYS).isdisjoint(spec.DELIVERY_FRONTMATTER_KEYS)


def test_tags_are_lower_case_sorted_and_checked():
    assert spec.normalize_tags([" IaC ", "iac", "hcl", ""]) == ["hcl", "iac"]
    assert spec.tag_issues(["ok-tag", "bad tag", "-x"]) == ["bad tag", "-x"]


@pytest.mark.parametrize(("path", "code"), [
    ("/etc/passwd", "skill_path_absolute"),
    ("C:/x", "skill_path_absolute"),
    ("../x", "skill_path_traversal"),
    ("a/../../x", "skill_path_traversal"),
    ("a\\b", "skill_path_invalid"),
    ("a\x00b", "skill_path_invalid"),
    ("", "skill_path_invalid"),
])
def test_unsafe_paths_are_refused(path, code):
    with pytest.raises(BundleError) as caught:
        bundle.normalize_path(path)
    assert caught.value.code == code


def test_paths_are_normalized():
    assert bundle.normalize_path("references/./a.md") == "references/a.md"
    assert bundle.normalize_path("a/../b.md") == "b.md"


def test_classification_of_bundle_files():
    assert bundle.classify("SKILL.md", "") == "instructions"
    assert bundle.classify("LICENSE", "") == "licence"
    assert bundle.classify(".mcp.json", "{}") == "manifest"
    assert bundle.classify("scripts/x.txt", "") == "script"
    assert bundle.classify("tool.py", "") == "script"
    assert bundle.classify("notes.txt", "#!/bin/sh\n") == "script"
    assert bundle.classify("assets/a.template", "") == "asset"
    assert bundle.classify("references/a.md", "") == "reference"
    assert bundle.classify("SECURITY.md", "") == "reference"


def test_manifest_and_digest_are_order_independent_and_change_with_content():
    first = [BundleFile("SKILL.md", "a"), BundleFile("references/x.md", "b")]
    entries = bundle.manifest(first)
    assert [entry["path"] for entry in entries] == ["SKILL.md", "references/x.md"]
    assert entries[0]["size"] == 1 and len(entries[0]["sha256"]) == 64
    digest = bundle.bundle_digest(entries)
    assert digest == bundle.bundle_digest(bundle.manifest(list(reversed(first))))
    assert digest != bundle.bundle_digest(bundle.manifest([BundleFile("SKILL.md", "a"),
                                                           BundleFile("references/x.md", "c")]))
    assert digest != bundle.bundle_digest(bundle.manifest([BundleFile("SKILL.md", "a"),
                                                           BundleFile("references/y.md", "b")]))


def test_bundle_limits():
    with pytest.raises(BundleError) as too_many:
        bundle.check_limits([BundleFile(f"f{index}.md", "x") for index in range(bundle.MAX_BUNDLE_FILES + 1)])
    assert too_many.value.code == "skill_bundle_too_many_files"
    assert len(bundle.check_limits([BundleFile(f"f{index}.md", "x") for index in range(bundle.MAX_BUNDLE_FILES)])) == 200
    with pytest.raises(BundleError) as large:
        bundle.check_limits([BundleFile("a.md", "x" * (bundle.MAX_FILE_BYTES + 1))])
    assert large.value.code == "skill_file_too_large"
    bundle.check_limits([BundleFile("a.md", "x" * bundle.MAX_FILE_BYTES)])
    with pytest.raises(BundleError) as total:
        bundle.check_limits([BundleFile(f"{index}.md", "x" * bundle.MAX_FILE_BYTES) for index in range(6)])
    assert total.value.code == "skill_bundle_too_large"
    with pytest.raises(BundleError) as duplicate:
        bundle.check_limits([BundleFile("a.md", "x"), BundleFile("a.md", "y")])
    assert duplicate.value.code == "skill_path_duplicate"


def test_decode_text_refuses_binary():
    assert bundle.decode_text("a", "ü".encode()) == "ü"
    for data in (b"\x00abc", b"\xff\xfe"):
        with pytest.raises(BundleError) as caught:
            bundle.decode_text("a", data)
        assert caught.value.code == "skill_file_binary"


def test_extension_normalization_and_delivered_body():
    normalized = extension.normalize_extension({
        "tools": {"octryx_claude": {"required": ["Bash(terraform validate *)", "Bash(terraform validate *)"]}},
        "safety_rules": ["Never apply"], "allowed_roles": ["Operator", "operator"], "output_contract": {"format": "md"},
    })
    assert normalized["tools"]["octryx_claude"]["required"] == ["Bash(terraform validate *)"]
    assert normalized["tools"]["platform_chat"] == {"required": [], "optional": []}
    assert normalized["allowed_roles"] == ["operator"]
    body = extension.delivered_body("# Title\n", normalized)
    assert body == "# Title\n\n## Output\n\n- **format**: md\n\n## Safety rules\n\n- Never apply\n"
    assert extension.delivered_body("# T\n", extension.normalize_extension({})) == "# T\n"


def test_card_text_uses_the_outline_outside_code_fences():
    body = "# A\n\n```\n# not a heading\n```\n\n## B\n#### too deep\n"
    assert extension.outline(body) == ["- A", "  - B"]
    assert extension.card_text("Desc", body, {}) == "Desc\n\nSections:\n- A\n  - B"
    assert extension.card_text("Desc", body, {"card_content": "Manual"}) == "Manual"
    assert extension.card_text("Desc", "no headings", {}) == "Desc"
    assert extension.token_cost("abcd") == 1 and extension.token_cost("abcde") == 2
