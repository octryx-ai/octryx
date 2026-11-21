"""Gemma's nested tool arguments sent as text are read back."""

from __future__ import annotations

from pathlib import Path

from app.services.lenient_arguments import structured

SAMPLE = (Path(__file__).parent / "fixtures" / "gemma_criteria_argument.txt").read_text(encoding="utf-8")


def test_the_live_gemma_criteria_string_becomes_the_five_criteria():
    criteria = structured(SAMPLE, name="criteria")
    assert [item["id"] for item in criteria] == [
        "schema_creation", "member_crud", "inventory_crud", "trip_crud", "trip_validation"]
    assert criteria[0]["command"] == ".venv/bin/python -m pytest -v tests/test_repository.py"
    assert criteria[0]["tests"] == [{"id": "tests/test_repository.py::test_schema_creation", "role": "new"}]


def test_plain_json_text_and_real_lists_pass_and_unreadable_text_stays_text():
    assert structured('[{"id": "a"}]') == [{"id": "a"}]
    assert structured([{"id": "a"}]) == [{"id": "a"}]
    assert structured('{criteria: [{id: "a"}], summary: "s"}', name="criteria") == [{"id": "a"}]
    assert structured("no structure here") == "no structure here"
    assert structured('{id: "a"}', kind=dict) == {"id": "a"}


def test_flat_criteria_lines_become_the_structured_contract():
    from app.services.lenient_arguments import criteria_from_lines

    lines = [
        "AC1 | Tables are created on an empty database | .venv/bin/python -m pytest -v tests/test_repository.py "
        "| tests/test_repository.py::test_schema_creation, tests/test_x.py::test_old (regression)",
        "AC2 | The README explains the start | manual: read by the product owner | -",
    ]
    assert criteria_from_lines(lines) == [
        {"id": "AC1", "text": "Tables are created on an empty database",
         "command": ".venv/bin/python -m pytest -v tests/test_repository.py",
         "tests": [{"id": "tests/test_repository.py::test_schema_creation", "role": "new"},
                   {"id": "tests/test_x.py::test_old", "role": "regression"}]},
        {"id": "AC2", "text": "The README explains the start", "manual_only": True,
         "manual_reason": "read by the product owner"},
    ]
