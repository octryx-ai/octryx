from __future__ import annotations

from app.services.secure_work.plans.acceptance_coverage import (
    acceptance_coverage_blockers,
    derive_unit_acceptance_criteria,
    evaluate_acceptance_coverage,
    normalize_acceptance_criteria,
)

GREP_BLOCKS = "grep -rn 'removed {' terraform && exit 1 || exit 0"
GREP_CONFIG = "python3 check_orphaned_tfvars.py terraform/base"
VALIDATION_PLAN = [
    {"command": GREP_BLOCKS, "source": "change_unit"},
    {"command": GREP_CONFIG, "source": "llm_inference"},
    {"command": "Manual verification required", "source": "manual_required"},
]


def test_normalize_assigns_ids_and_drops_empty_entries():
    criteria = normalize_acceptance_criteria(
        [
            {"text": "Remove removed/moved blocks", "validation_commands": [GREP_BLOCKS, "  "]},
            {"text": "   "},
            "not-a-dict",
            {"id": "AC-CONFIG", "text": "Clean prod/nonprod config", "validation_commands": [GREP_CONFIG]},
        ]
    )
    assert [entry["id"] for entry in criteria] == ["AC1", "AC-CONFIG"]
    assert criteria[0]["validation_commands"] == [GREP_BLOCKS]


def test_coverage_marks_placeholder_commands_as_not_enforceable():
    criteria = normalize_acceptance_criteria(
        [
            {"id": "AC1", "text": "blocks", "validation_commands": [GREP_BLOCKS]},
            {"id": "AC2", "text": "manual only", "validation_commands": ["Manual verification required"]},
            {"id": "AC3", "text": "no command"},
        ]
    )
    report = evaluate_acceptance_coverage(criteria, VALIDATION_PLAN)
    assert report["uncovered_ids"] == ["AC2", "AC3"]
    assert report["criteria"][0]["covered"] is True


def test_blockers_empty_for_full_coverage():
    criteria = normalize_acceptance_criteria(
        [{"id": "AC1", "text": "blocks", "validation_commands": [GREP_BLOCKS]}]
    )
    assert (
        acceptance_coverage_blockers(
            plan_type="coding_change",
            criteria=criteria,
            validation_plan=VALIDATION_PLAN,
            has_change_units=True,
            human_verified_ids=[],
        )
        == []
    )


def test_blockers_list_uncovered_criteria():
    criteria = normalize_acceptance_criteria(
        [
            {"id": "AC1", "text": "blocks", "validation_commands": [GREP_BLOCKS]},
            {"id": "AC2", "text": "clean the prod and nonprod config"},
        ]
    )
    blockers = acceptance_coverage_blockers(
        plan_type="coding_change",
        criteria=criteria,
        validation_plan=VALIDATION_PLAN,
        has_change_units=True,
        human_verified_ids=[],
    )
    assert len(blockers) == 1
    assert "AC2" in blockers[0]


def test_human_verified_takeover_unblocks_and_unknown_id_blocks():
    criteria = normalize_acceptance_criteria([{"id": "AC2", "text": "config cleanup"}])
    assert (
        acceptance_coverage_blockers(
            plan_type="coding_change",
            criteria=criteria,
            validation_plan=VALIDATION_PLAN,
            has_change_units=False,
            human_verified_ids=["AC2"],
        )
        == []
    )
    blockers = acceptance_coverage_blockers(
        plan_type="coding_change",
        criteria=criteria,
        validation_plan=VALIDATION_PLAN,
        has_change_units=False,
        human_verified_ids=["AC2", "AC99"],
    )
    assert len(blockers) == 1 and "AC99" in blockers[0]


def test_coding_plan_without_criteria_is_blocked_but_analysis_is_not():
    kwargs = {"criteria": [], "validation_plan": VALIDATION_PLAN, "human_verified_ids": []}
    assert acceptance_coverage_blockers(plan_type="coding_change", has_change_units=False, **kwargs)
    assert acceptance_coverage_blockers(plan_type="", has_change_units=True, **kwargs)
    assert acceptance_coverage_blockers(plan_type="analysis", has_change_units=False, **kwargs) == []


def test_derive_unit_criteria_uses_unit_scope_and_commands():
    criteria = derive_unit_acceptance_criteria(
        [
            {"scope": "Delete the todelete stack", "validation_commands": [GREP_BLOCKS]},
            {"repository_name": "infra", "validation_commands": []},
        ]
    )
    assert criteria[0]["source"] == "change_unit"
    assert criteria[0]["validation_commands"] == [GREP_BLOCKS]
    report = evaluate_acceptance_coverage(criteria, VALIDATION_PLAN)
    assert report["uncovered_ids"] == ["AC2"]
