"""A one-click suggestion must run once applied.

A suggestion like ``return 0.0 if total >= FREE_SHIPPING_FROM else SHIPPING_FLAT_RATE`` where nothing in the file
defines ``SHIPPING_FLAT_RATE`` gives a ``NameError`` on click. Such a suggestion is posted as text with the reason; one
that runs keeps its block, and the posted block applied to the file must import and work."""

import re

from app.services.pr_review_bot.diff_lines import parse_diff
from app.services.pr_review_bot.render import build_post
from app.services.pr_review_bot.suggestion_names import applied, problem

HEAD = '"""Order totals of the Demo Shop."""\n\nfrom __future__ import annotations\n\nfrom dataclasses import dataclass\n\n\n@dataclass(frozen=True)\nclass Line:\n    """One order line: a product\'s unit price and how many of it."""\n\n    product: str\n    unit_price: float\n    quantity: int = 1\n\n\ndef subtotal(lines: list[Line]) -> float:\n    """The sum of all lines before any discount."""\n    return round(sum(line.unit_price * line.quantity for line in lines), 2)\n\n\ndef order_total(lines: list[Line], discount_percent: float = 0) -> float:\n    """The amount to pay: the subtotal less the discount (a percentage of the subtotal, 0 to 100)."""\n    if not 0 <= discount_percent <= 100:\n        raise ValueError("discount_percent must be between 0 and 100")\n    return round(subtotal(lines) - discount_percent, 2)\n\n\nFREE_SHIPPING_FROM = 50\n\n\ndef shipping_cost(total: float) -> float:\n    """Shipping is free from FREE_SHIPPING_FROM on, else a flat 4.90."""\n    if total > FREE_SHIPPING_FROM:\n        return 0\n    return 4.9\n'
DIFF = 'diff --git a/shop/pricing.py b/shop/pricing.py\nindex 07669f0..632c177 100644\n--- a/shop/pricing.py\n+++ b/shop/pricing.py\n@@ -24,3 +24,13 @@ def order_total(lines: list[Line], discount_percent: float = 0) -> float:\n     if not 0 <= discount_percent <= 100:\n         raise ValueError("discount_percent must be between 0 and 100")\n     return round(subtotal(lines) - discount_percent, 2)\n+\n+\n+FREE_SHIPPING_FROM = 50\n+\n+\n+def shipping_cost(total: float) -> float:\n+    """Shipping is free from FREE_SHIPPING_FROM on, else a flat 4.90."""\n+    if total > FREE_SHIPPING_FROM:\n+        return 0\n+    return 4.9\n'
F3 = "    return 0.0 if total >= FREE_SHIPPING_FROM else SHIPPING_FLAT_RATE"


def _comment(line: int, suggestion: str, provider: str = "gitlab", sources: dict | None = None):
    review = {"verdict": "changes", "summary": "s", "findings": [{
        "id": "F3", "severity": "low", "file": "shop/pricing.py", "line": line, "fix": "f", "suggestion": suggestion}]}
    facts = {"sha": "ec0da47", "sources": {"shop/pricing.py": HEAD} if sources is None else sources}
    return build_post(review, parse_diff(DIFF), provider=provider, facts=facts).comments[0]


def test_the_live_suggestion_with_an_undefined_name_is_posted_as_text_with_the_reason():
    comment = _comment(36, F3)  # on the ``return 4.9`` it rewrites
    assert "suggestion:" not in comment.body and "```suggestion" not in comment.body
    assert "apply by hand and complete it: it uses `SHIPPING_FLAT_RATE`, which the file does not define" in comment.body
    assert F3 in comment.body and comment.start_line == 0
    assert "```suggestion" not in _comment(36, F3, provider="github").body
    live = _comment(34, F3)  # where the reviewer put it: the ``if`` line, which a click would have replaced
    assert "suggestion:" not in live.body and "apply by hand" in live.body


def test_a_suggestion_on_a_line_it_does_not_rewrite_moves_to_the_line_it_does():
    """A finding on line 32 (the ``def``) for ``if total >= FREE_SHIPPING_FROM:``, which rewrites line 34."""
    comment = _comment(32, "    if total >= FREE_SHIPPING_FROM:")
    assert comment.line == 34 and "suggestion:-0+0" in comment.body


def test_a_suggestion_that_runs_keeps_its_block_and_applied_it_works():
    good = "    if total >= FREE_SHIPPING_FROM:"
    comment = _comment(34, good)
    block = re.search(r"```suggestion:-(\d+)\+0\n(.*?)\n```", comment.body, re.S)
    assert block is not None
    namespace: dict = {}
    exec(compile(applied(HEAD, comment.line - int(block.group(1)), comment.line, block.group(2)), "p.py", "exec"),
         namespace)  # noqa: S102 - the fixture's own code
    assert namespace["shipping_cost"](50) == 0 and namespace["shipping_cost"](49.99) == 4.9


def test_a_name_the_suggestion_or_the_file_binds_is_known():
    defined = "    SHIPPING_FLAT_RATE = 4.9\n    return 0.0 if total >= FREE_SHIPPING_FROM else SHIPPING_FLAT_RATE"
    assert problem("shop/pricing.py", HEAD, 36, 36, defined) == ""
    assert problem("shop/pricing.py", HEAD, 36, 36, "    return round(float(total) * 0, 2)") == ""  # builtins
    assert problem("shop/pricing.py", HEAD, 36, 36, "    return dataclass") == ""  # imported at the top


def test_a_suggestion_that_breaks_the_syntax_is_refused():
    assert problem("shop/pricing.py", HEAD, 34, 34, "    if total >= FREE_SHIPPING_FROM").startswith(
        "the file would not parse")


def test_without_the_file_or_for_another_language_the_block_stays():
    assert problem("web/app.ts", "const a = 1;", 1, 1, "const a = b;") == ""
    assert "suggestion:-0+0" in _comment(36, F3, sources={}).body
