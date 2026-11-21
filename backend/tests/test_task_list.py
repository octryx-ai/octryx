"""The readiness check's task list becomes the agreed work: contract, gate, review."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.workflow_runs.task_list import (
    missing_proofs,
    parse,
    render,
    run_task_list,
    task_list_result,
)

ANSWER = """Ready: no open questions.

Task list:
T1. GET /api/recipes searches dish, recipe and ingredient names | proof: tests/benchmark/test_search.py::test_text_search
T2. Dish cards in a grid with image area, name, time, calories and chips | proof: tests/system/test_search_system.py::test_cards
- **T3.** Previous disabled on page 1 | proof: `tests/system/test_search_system.py::test_paging_disabled`
T2. a duplicate number is ignored | proof: tests/x.py::test_dup
"""


def _patch(*tests):
    lines = []
    for path, name in tests:
        lines += [f"diff --git a/{path} b/{path}", f"+def {name}(page):", "+    assert True"]
    return {"base": "a" * 40, "patch": "\n".join(lines) + "\n"}


def test_the_answer_s_task_list_is_parsed_in_order():
    items = parse(ANSWER)
    assert [item["id"] for item in items] == ["T1", "T2", "T3"]
    assert items[2] == {"id": "T3", "text": "Previous disabled on page 1",
                        "proof": "tests/system/test_search_system.py::test_paging_disabled",
                        "proofs": ["tests/system/test_search_system.py::test_paging_disabled"]}
    assert parse("Ready: no open questions") == []
    assert render(items).splitlines()[0].startswith("T1. GET /api/recipes")


def test_the_run_s_task_list_comes_from_the_readiness_answer():
    run = SimpleNamespace(context={"answers": {"readiness": ANSWER}})
    assert len(run_task_list(run)) == 3
    assert run_task_list(SimpleNamespace(context={})) == []


def test_every_item_needs_its_proof_test_in_the_change():
    items = parse(ANSWER)
    partial = _patch(("tests/benchmark/test_search.py", "test_text_search"))
    assert missing_proofs(items, partial) == [
        "T2 (tests/system/test_search_system.py::test_cards)",
        "T3 (tests/system/test_search_system.py::test_paging_disabled)"]
    result = task_list_result(items, partial)
    assert result.blocking and "T2" in result.description and "T1" not in result.description
    full = _patch(("tests/benchmark/test_search.py", "test_text_search"),
                  ("tests/system/test_search_system.py", "test_cards"),
                  ("tests/system/test_search_system.py", "test_paging_disabled"))
    assert task_list_result(items, full) is None
    assert task_list_result(items, {"base": "a", "truncated": True, "patch": ""}) is None  # cannot judge
    assert task_list_result([], partial) is None


async def test_a_long_readiness_answer_keeps_its_whole_task_list():
    # A small model may ask many questions before the list; a 4000-character answer cap would cut the list.
    from app.services.workflow_runs.octryx.stop_answers import _keep_task_list

    questions = "\n".join(f"{n}. A long open question about the spec, section 8.2, with a proposal. " * 6
                          for n in range(1, 15))
    tasks = "\n".join(f"T{n}. item {n} | proof: tests/system/test_x.py::test_item_{n}" for n in range(1, 12))
    answer = f"Not ready.\n{questions}\n\nTask list:\n{tasks}"
    assert len(answer) > 4000
    run = SimpleNamespace(id="r1", work_item_id=None, context={"answers": {"readiness": answer[:4000]}})
    node = SimpleNamespace(config={"workflow_contract": {"capability_class": "read_only"}})
    await _keep_task_list(None, run, node, answer)
    assert [item["id"] for item in run_task_list(run)] == [f"T{n}" for n in range(1, 12)]
    build = SimpleNamespace(id="r2", work_item_id=None, context={})
    await _keep_task_list(None, build, SimpleNamespace(config={"workflow_contract": {"capability_class": "change"}}),
                          answer)
    assert build.context == {}  # only the readiness check sets the list


def test_no_task_is_dropped_two_proofs_a_note_or_none():
    # Tasks that name two proofs or a "(screenshot ...)" note must not be dropped.
    answer = "\n".join([
        "Not ready.", "1. A question?", "", "Task list:",
        "T1. one | proof: tests/a.py::test_one",
        "T2. two proofs | proof: tests/a.py::test_two and tests/system/b.py::test_two_ui",
        "T3. comma | proof: tests/a.py::test_x, tests/a.py::test_y",
        "T4. screen | proof: tests/system/b.py::test_screen (screenshot \"profile\")",
        "T5. no proof named yet",
        *[f"T{n}. item {n} | proof: tests/a.py::test_{n}" for n in range(6, 41)],
    ])
    items = parse(answer)
    assert [item["id"] for item in items] == [f"T{n}" for n in range(1, 41)]
    assert items[1]["proofs"] == ["tests/a.py::test_two", "tests/system/b.py::test_two_ui"]
    assert items[2]["proofs"] == ["tests/a.py::test_x", "tests/a.py::test_y"]
    assert items[3]["proofs"] == ["tests/system/b.py::test_screen"] and items[4]["proofs"] == []
    change = _patch(("tests/a.py", "test_one"), ("tests/a.py", "test_two"), ("tests/a.py", "test_x"),
                    ("tests/a.py", "test_y"), ("tests/system/b.py", "test_screen"))
    missing = missing_proofs(items[:5], change)
    assert missing == ["T2 (tests/system/b.py::test_two_ui)", "T5 (no proof test named)"]
    assert "T2. two proofs | proof: tests/a.py::test_two, tests/system/b.py::test_two_ui" in render(items)
