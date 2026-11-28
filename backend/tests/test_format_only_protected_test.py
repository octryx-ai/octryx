"""A formatting-only Edit of a protected test passes; any other change of it stays refused (refusing it would pause
the run at its loop limit when ``ruff format --check`` wants the test reformatted)."""

from __future__ import annotations

import pytest

from app.services.workflow_runs.octryx.format_only import same_program
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.test_workflow_run_octryx_hardening import _confirmed
from tests.workflow_run_octryx_support import ROOT, _decide, _hook

pytestmark = pytest.mark.usefixtures("scripted_pool")

WRAPPED = ('def test_discount_percent_is_a_percentage_of_the_subtotal(self):\n        self.assertEqual(\n'
           '            order_total([Line("mug", 50.00)], discount_percent=10), 45.00\n        )')
JOINED = ('def test_discount_percent_is_a_percentage_of_the_subtotal(self):\n        self.assertEqual(order_total('
          '[Line("mug", 50.00)], discount_percent=10), 45.00)')


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)


@pytest.mark.asyncio
async def test_the_formatter_s_wish_on_the_confirmed_test_passes_and_a_real_change_does_not(db):
    _run, gateway, key, workspace_id = await _confirmed(db)

    async def edit(old: str, new: str) -> dict:
        hook = {**_hook("Edit", file_path=f"{ROOT}/tests/test_totals.py", old_string=old, new_string=new),
                "workflow_run_facts": {"target_exists": True}}
        return await _decide(db, gateway, key, workspace_id, hook)

    assert (await edit(WRAPPED, JOINED))["decision"] == "allow"
    weakened = JOINED.replace("45.00)", "40.00)")
    assert (await edit(WRAPPED, weakened))["reason"] == "confirmed_test_protected"
    assert (await edit(WRAPPED, JOINED + "\n        self.skipTest('later')"))["reason"] == \
        "confirmed_test_protected"


@pytest.mark.parametrize(("old", "new", "same"), [
    ("x = f(a,\n      b,\n)", "x = f(a, b)", True),
    ("s = 'mug'", 's = "mug"', True),
    ("x = f(a, b)", "x = f(b, a)", False),
    ("assert x == 1", "assert x == 1 or True", False),
    ("if a:\n    b()\n", "if a:\n    pass\nb()\n", False),
])
def test_python_layout_is_compared_by_its_tokens(old, new, same):
    assert same_program(old, new, "tests/test_x.py") is same


def test_other_stacks_compare_by_a_generic_tokenizer_and_unknown_files_stay_protected():
    assert same_program("expect(f(1,\n  2,\n), 3);", "expect(f(1, 2), 3);", "test/a_test.dart")
    assert not same_program("expect(f(1), 3);", "expect(f(1), 4);", "test/a.test.ts")
    assert not same_program("x", "x ", "tests/data.csv")
