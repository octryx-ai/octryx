"""The context pack: built from the checkout by ast-grep and the FastAPI adapter, matched to the Work item with fixed
weights, capped, cached by content fingerprint, put in front of a writing phase's first prompt once."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from octryx_claude import context_pack, context_pack_structure
from octryx_claude.context_pack_languages import LANGUAGES, rules

AST_GREP = Path(sys.executable).parent / "ast-grep"
ROUTES = '''from fastapi import APIRouter, Depends
from shop.auth import current_customer
from shop.orders import cancel_order

router = APIRouter(prefix="/orders", dependencies=[Depends(current_customer)])


@router.post("/{order_id}/cancel")
async def cancel(order_id: str, db=Depends(open_db)):
    return cancel_order(order_id)
'''
ORDERS = '''def cancel_order(order_id):
    return refund_payment(order_id)


def refund_payment(order_id):
    return order_id
'''
TEST = '''from shop.orders import cancel_order


def test_cancel_order():
    assert cancel_order("1")
'''
ITEM = {"key": "SHOP-7", "title": "Cancelled orders are refunded",
        "description": "`cancel_order` must refund the payment. Route: POST /orders/{order_id}/cancel"}


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def checkout(tmp_path, monkeypatch) -> Path:
    assert AST_GREP.exists(), "ast-grep-cli is a declared dependency of the launcher"
    monkeypatch.setattr(context_pack_structure, "ast_grep", lambda: str(AST_GREP))
    root = tmp_path / "repo"
    for name, text in {"shop/routes.py": ROUTES, "shop/orders.py": ORDERS, "shop/auth.py": "def current_customer():\n"
                       "    return 1\n", "tests/test_orders.py": TEST, "README.md": "Shop\n"}.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    _git(root, "init", "-q")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t.invalid", "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-qm", "base")
    return root


def _request(**item) -> dict:
    return {"phase": "implement", "app_folder": ".", "item": {**ITEM, **item}}


def test_the_pack_names_the_symbol_its_callers_route_and_tests(tmp_path, checkout):
    text, event = context_pack.build(tmp_path / "state", str(checkout), _request())
    assert "`cancel_order` shop/orders.py:1; called from shop/routes.py:10 `cancel`" in text
    assert ("POST /orders/{order_id}/cancel -> `cancel` shop/routes.py:9 [dependencies: current_customer, "
            "open_db]") in text
    assert "- tests/test_orders.py" in text and "not a model" in text
    assert "refund_payment" in text, "two words of the item in its name"
    assert (event["kind"], event["phase"], event["cached"], event["routes"], event["tests"]) == (
        "context_pack", "implement", False, 1, 1)
    assert event["chars"] == len(text) <= context_pack.MAX_CHARS and event["text"] == text


def test_the_same_checkout_gives_the_same_pack_from_the_cache_until_a_file_changes(tmp_path, checkout):
    state = tmp_path / "state"
    first, before = context_pack.build(state, str(checkout), _request())
    again, event = context_pack.build(state, str(checkout), _request())
    assert (again, event["cached"], event["fingerprint"]) == (first, True, before["fingerprint"])
    (checkout / "shop" / "orders.py").write_text(ORDERS + "\n\ndef cancel_order_later(order_id):\n    return 1\n")
    _changed, event = context_pack.build(state, str(checkout), _request())
    assert (event["cached"], event["definitions"]) == (False, before["definitions"] + 1)
    assert event["fingerprint"] != before["fingerprint"]


def test_prose_words_alone_point_at_nothing(tmp_path, checkout):
    text, event = context_pack.build(tmp_path / "state", str(checkout), _request(
        title="Make the shop faster", description="Customers wait too long."))
    assert (text, event["symbols"], event["chars"]) == ("", 0, 0)


def test_a_writing_phase_gets_the_pack_once_in_front_of_its_first_prompt(tmp_path, checkout):
    offer = {"prompt": "Implement SHOP-7.", "folder": str(checkout), "workflow_run": "run-1",
             "context_pack": _request()}
    prompt, event = context_pack.with_context_pack(tmp_path, offer, "session-1")
    assert prompt.startswith("Context pack") and prompt.endswith(f"{context_pack.FOLLOWS}\n\nImplement SHOP-7.")
    assert event is not None and event["symbols"] >= 1
    assert context_pack.with_context_pack(tmp_path, offer, "session-1") == ("Implement SHOP-7.", None)
    assert context_pack.with_context_pack(tmp_path, offer, "session-2")[1] is not None, "a new session gets it"
    assert context_pack.with_context_pack(tmp_path, {**offer, "context_pack": None}, "s") == ("Implement SHOP-7.",
                                                                                            None)


def test_a_failing_build_leaves_the_prompt_and_says_why(tmp_path, checkout, monkeypatch):
    def broken(*_args):
        raise OSError("disk")

    monkeypatch.setattr(context_pack, "build", broken)
    offer = {"prompt": "p", "folder": str(checkout), "workflow_run": "r", "context_pack": _request()}
    assert context_pack.with_context_pack(tmp_path, offer, "s") == ("p", {"kind": "context_pack", "phase":
                                                                        "implement", "error": "OSError"})


def test_without_ast_grep_the_routes_still_lead_to_their_handler(tmp_path, checkout, monkeypatch):
    monkeypatch.setattr(context_pack_structure, "ast_grep", lambda: None)
    text, event = context_pack.build(tmp_path / "state", str(checkout), _request(description="Route: POST "
                                                                                 "/orders/{order_id}/cancel"))
    assert (event["definitions"], text) == (0, "")


def test_the_pack_stays_within_its_cap(tmp_path, checkout):
    many = "".join(f"def refund_payment_step_{index}(order_id):\n    return cancel_order(order_id)\n\n"
                   for index in range(400))
    (checkout / "shop" / "steps.py").write_text(many)
    text, event = context_pack.build(tmp_path / "state", str(checkout), _request(
        description=" ".join(f"`refund_payment_step_{index}`" for index in range(400))))
    assert len(text) <= context_pack.MAX_CHARS and event["symbols"] == context_pack.MAX_SYMBOLS


SAMPLES = {
    "python": ("a.py", "from a.b import c\ndef cancel():\n    c()\n"),
    "typescript": ("a.ts", 'import { y } from "./z";\nconst cancel = (a: number) => y(a);\n'),
    "tsx": ("a.tsx", 'import x from "./y";\nfunction cancel() { return x(); }\n'),
    "javascript": ("a.js", 'import { x } from "./api";\nexport function cancel() { return x(1); }\n'),
    "java": ("A.java", "import java.util.List;\nclass A { void cancel() { helper(); } }\n"),
    "go": ("a.go", 'package main\nimport "fmt"\nfunc cancel() { fmt.Println("x") }\n'),
    "rust": ("a.rs", "use std::fmt;\nfn cancel() { helper(); }\n"),
    "csharp": ("A.cs", "using System;\nclass A { void cancel() { Helper(); } }\n"),
    "ruby": ("a.rb", "class A\n  def cancel\n    helper(1)\n  end\nend\n"),
    "php": ("a.php", "<?php\nuse App\\Order;\nfunction cancel() { helper(); }\n"),
}


@pytest.mark.parametrize("language", sorted(LANGUAGES))
def test_every_listed_language_yields_definitions_calls_and_imports(tmp_path, monkeypatch, language):
    monkeypatch.setattr(context_pack_structure, "ast_grep", lambda: str(AST_GREP))
    name, source = SAMPLES[language]
    (tmp_path / name).write_text(source)
    found = context_pack_structure.read_structure(str(tmp_path), [name])
    assert "cancel" in {item[1] for item in found.definitions}, rules({language})
    assert found.calls == [] or all(call[2] in {"cancel"} for call in found.calls), "only calls to defined names"


@pytest.mark.asyncio
async def test_the_device_job_puts_the_pack_in_front_of_the_run_turn_and_reports_it(state, tmp_path, checkout,
                                                                                      monkeypatch):
    from octryx_claude import run_wip
    from tests.device_jobs_support import FakeDriver, _manager, _offer, _settle

    monkeypatch.setattr(run_wip, "push_run_wip", lambda *args: {"state": "unchanged"})
    driver = FakeDriver()
    manager, channel, repo = _manager(state, tmp_path, driver=driver)
    assert repo == checkout
    await manager.handle("job_offer", _offer(repo, workflow_run_id="run-1", context_pack=_request()))
    await _settle(manager)
    assert driver.calls[0]["prompt"].startswith("Context pack")
    assert driver.calls[0]["prompt"].endswith("Run the tests")
    [event] = [body for body in channel.of("job_event") if body.get("kind") == "context_pack"]
    assert event["turn_id"] == "t1" and "cancel_order" in event["text"]
    await manager.handle("job_offer", _offer(repo, job_id="dj_2", turn_id="t2"))  # a chat turn: no pack
    await _settle(manager)
    assert driver.calls[1]["prompt"] == "Run the tests"


def test_a_file_the_item_names_is_listed_even_without_a_matching_name(tmp_path, checkout):
    text, event = context_pack.build(tmp_path / "state", str(checkout), _request(
        title="Tighten the login", description="Nothing here names code.", paths=["shop/au*.py", "shop/new.py"]))
    assert "- shop/auth.py (named by the item)" in text and "shop/new.py" not in text
    assert event["files"] == 1


def test_a_test_whose_name_matches_the_item_points_at_the_file_it_imports(tmp_path, checkout):
    (checkout / "tests" / "test_rounding.py").write_text(
        "from shop.orders import refund_payment\n\n\ndef test_partial_refunds_are_rounded_to_cents():\n"
        "    assert refund_payment(1)\n")
    text, _event = context_pack.build(tmp_path / "state", str(checkout), _request(
        title="Partial refund payments are rounded to cents", description="`refund_payment` rounds half up."))
    assert "- tests/test_rounding.py" in text
    assert "- shop/orders.py (its tests match the item)" in text
    assert "shop/routes.py" not in text, "below the floor: left out rather than filling the cap"


def test_a_weak_match_sends_no_pack_but_still_reports_it(tmp_path, checkout):
    weak = _request(title="Partial refund payments are rounded to cents",
                    description="A partial refund rounds half up.")
    text, event = context_pack.build(tmp_path / "state", str(checkout), weak)
    assert (text, event["confident"], event["chars"]) == ("", 0, 0), "no name, route or path, and few names match"
    offer = {"prompt": "Implement it.", "folder": str(checkout), "workflow_run": "r", "context_pack": weak}
    prompt, reported = context_pack.with_context_pack(tmp_path, offer, "s")
    assert (prompt, reported["confident"]) == ("Implement it.", 0)
    assert context_pack.build(tmp_path / "state", str(checkout), _request())[1]["confident"] == 1
