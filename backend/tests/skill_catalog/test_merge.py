"""The 3-way merge (pure): per-file rules, diff3 regions, conflicts, relocation, resolutions."""

from __future__ import annotations

import pytest

from app.services.skill_catalog.errors import SkillCatalogError
from app.services.skill_catalog.merge import merge_bundle, merge_lines, resolved_files

BASE = "a\nb\nc\nd\ne\n"


def _kinds(base: str, ours: str, theirs: str) -> list[str]:
    return [kind for kind, _ in merge_lines(base.splitlines(True), ours.splitlines(True), theirs.splitlines(True))]


def test_merge_lines_separates_local_upstream_same_and_conflicting_hunks():
    assert _kinds(BASE, BASE.replace("b\n", "B\n"), BASE.replace("d\n", "D\n")) == [
        "unchanged", "ours", "unchanged", "theirs", "unchanged"]
    assert _kinds(BASE, BASE.replace("c\n", "X\n"), BASE.replace("c\n", "X\n")) == ["unchanged", "same", "unchanged"]
    conflict = merge_lines(BASE.splitlines(True), BASE.replace("c\n", "O\n").splitlines(True),
                           BASE.replace("c\n", "T\n").splitlines(True))
    assert [kind for kind, _ in conflict] == ["unchanged", "conflict", "unchanged"]
    assert conflict[1][1] == (["c\n"], ["O\n"], ["T\n"])


def test_per_file_rules():
    merged = merge_bundle(
        {"same.md": "x\n", "local.md": "x\n", "up.md": "x\n", "gone.md": "x\n", "both.md": "x\n"},
        {"same.md": "x\n", "local.md": "mine\n", "up.md": "x\n", "gone.md": "x\n", "both.md": "y\n",
         "mine-only.md": "m\n"},
        {"same.md": "x\n", "local.md": "x\n", "up.md": "theirs\n", "both.md": "y\n", "new.md": "n\n"})
    statuses = {item["path"]: item["status"] for item in merged["report"]["files"]}
    assert statuses == {"same.md": "unchanged", "local.md": "kept_local", "up.md": "took_upstream",
                        "gone.md": "removed_upstream", "both.md": "same_change", "mine-only.md": "kept_local",
                        "new.md": "added_upstream"}
    assert merged["files"] == {"same.md": "x\n", "local.md": "mine\n", "up.md": "theirs\n", "both.md": "y\n",
                               "mine-only.md": "m\n", "new.md": "n\n"}
    assert merged["report"]["conflicts"] == []


def test_a_file_changed_locally_and_deleted_upstream_is_a_file_conflict():
    merged = merge_bundle({"a.md": "x\n"}, {"a.md": "mine\n"}, {})
    conflict = merged["report"]["conflicts"][0]
    assert conflict["kind"] == "file" and conflict["theirs"] == [] and "a.md" not in merged["files"]
    keep = resolved_files(merged["files"], {**merged["report"], "resolutions": {conflict["id"]: {"choice": "mine"}}})
    assert keep == {"a.md": "mine\n"}
    drop = resolved_files(merged["files"], {**merged["report"],
                                            "resolutions": {conflict["id"]: {"choice": "upstream"}}})
    assert drop == {}


def test_both_sides_adding_the_same_path_differently_conflicts():
    merged = merge_bundle({}, {"n.md": "ours\n"}, {"n.md": "theirs\n"})
    assert merged["report"]["conflicts"][0]["kind"] == "hunk" and merged["files"]["n.md"] == "theirs\n"


def test_relocation_needs_exactly_one_new_upstream_file_with_the_base_block():
    base = {"SKILL.md": "# S\n\n- one\n- two\n\nend\n"}
    ours = {"SKILL.md": "# S\n\n- one\n- two\n- mine\n\nend\n"}
    single = merge_bundle(base, ours, {"SKILL.md": "# S\n\nSee LIST.md\n\nend\n", "LIST.md": "# L\n- one\n- two\n"})
    relocation = single["report"]["conflicts"][0]["relocation"]
    assert relocation["path"] == "LIST.md" and relocation["line"] == 2 and relocation["after_line"] == 3
    report = {**single["report"], "resolutions": {single["report"]["conflicts"][0]["id"]: {"choice": "relocate"}}}
    assert resolved_files(single["files"], report)["LIST.md"] == "# L\n- one\n- two\n- mine\n"
    twice = merge_bundle(base, ours, {"SKILL.md": "# S\n\nSee\n\nend\n", "A.md": "- one\n- two\n",
                                      "B.md": "- one\n- two\n"})
    assert twice["report"]["conflicts"][0]["relocation"] is None
    kept_upstream = merge_bundle(base, ours, {"SKILL.md": "# S\n\nIntro\n\nend\n\n## List\n- one\n- two\n",
                                              "LIST.md": "- one\n- two\n"})
    assert kept_upstream["report"]["conflicts"][0]["relocation"] is None  # the block still lives in SKILL.md
    existing = merge_bundle({**base, "LIST.md": "- one\n- two\n"}, {**ours, "LIST.md": "- one\n- two\n"},
                            {"SKILL.md": "# S\n\nSee\n\nend\n", "LIST.md": "- one\n- two\n"})
    assert existing["report"]["conflicts"][0]["relocation"] is None  # only files new upstream qualify
    no_relocation = {**twice["report"], "resolutions": {twice["report"]["conflicts"][0]["id"]: {"choice": "relocate"}}}
    with pytest.raises(SkillCatalogError) as refused:
        resolved_files(twice["files"], no_relocation)
    assert refused.value.code == "skill_relocation_unavailable"


def test_manual_resolution_needs_text():
    merged = merge_bundle({"a.md": "x\n"}, {"a.md": "o\n"}, {"a.md": "t\n"})
    conflict_id = merged["report"]["conflicts"][0]["id"]
    with pytest.raises(SkillCatalogError) as refused:
        resolved_files(merged["files"], {**merged["report"], "resolutions": {conflict_id: {"choice": "manual"}}})
    assert refused.value.code == "skill_resolution_text_required"
    done = resolved_files(merged["files"], {**merged["report"],
                                            "resolutions": {conflict_id: {"choice": "manual", "text": "z\n"}}})
    assert done == {"a.md": "z\n"}


def test_conflict_ids_are_stable_for_the_same_inputs():
    first = merge_bundle({"a.md": BASE}, {"a.md": BASE.replace("c", "o")}, {"a.md": BASE.replace("c", "t")})
    second = merge_bundle({"a.md": BASE}, {"a.md": BASE.replace("c", "o")}, {"a.md": BASE.replace("c", "t")})
    assert first["report"]["conflicts"][0]["id"] == second["report"]["conflicts"][0]["id"]
