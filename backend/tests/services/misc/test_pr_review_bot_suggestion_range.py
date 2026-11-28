"""A one-click suggestion replaces exactly the lines it rewrites; the tests apply the posted suggestion the
way GitLab and GitHub do and run the resulting code."""

import re

import pytest

from app.services.pr_review_bot.diff_lines import parse_diff
from app.services.pr_review_bot.render import build_post
from app.services.pr_review_bot.suggestion_range import cover

DIFF = """diff --git a/shop/pricing.py b/shop/pricing.py
index 07669f0..92d4635 100644
--- a/shop/pricing.py
+++ b/shop/pricing.py
@@ -24,3 +24,12 @@ def order_total(lines: list[Line], discount_percent: float = 0) -> float:
     if not 0 <= discount_percent <= 100:
         raise ValueError("discount_percent must be between 0 and 100")
     return round(subtotal(lines) - discount_percent, 2)
+
+
+COUPONS = {"WELCOME10": 10, "SPRING25": 25}
+
+
+def apply_coupon(amount: float, code: str) -> float:
+    \"\"\"The amount after the coupon's percentage discount.\"\"\"
+    percent = COUPONS[code]
+    return amount - amount * percent / 100
"""
HEAD = [""] * 23 + [line[1:] for line in DIFF.splitlines()[5:]]  # line n of the file at HEAD[n - 1]
LIVE_SUGGESTION = """    percent = COUPONS.get(code.strip().upper())
    if percent is None:
        raise ValueError(f"unknown coupon code: {code}")
    return round(amount - amount * percent / 100, 2)"""


def _post(finding: dict, provider: str):
    review = {"verdict": "changes", "summary": "s", "findings": [{"id": "F1", "severity": "medium",
                                                                   "file": "shop/pricing.py", "fix": "f", **finding}]}
    return build_post(review, parse_diff(DIFF), provider=provider, facts={"sha": "e611384"}).comments[0]


def _apply_gitlab(comment) -> list[str]:
    match = re.search(r"(`{3,})suggestion:-(\d+)\+(\d+)\n(.*?)\n\1", comment.body, re.S)
    above, below, block = int(match.group(2)), int(match.group(3)), match.group(4).split("\n")
    return HEAD[: comment.line - above - 1] + block + HEAD[comment.line + below:]


def _apply_github(comment) -> list[str]:
    match = re.search(r"(`{3,})suggestion\n(.*?)\n\1", comment.body, re.S)
    first = comment.start_line or comment.line
    return HEAD[: first - 1] + match.group(2).split("\n") + HEAD[comment.line:]


def _coupon(lines: list[str]):
    source = "\n".join(line for line in lines[28:])  # COUPONS and apply_coupon, without the dataclass imports
    namespace: dict = {}
    exec(compile(source, "pricing.py", "exec"), namespace)  # noqa: S102 - the test's own fixture code
    return namespace["apply_coupon"]


@pytest.mark.parametrize("apply, provider", [(_apply_gitlab, "gitlab"), (_apply_github, "github")])
def test_the_live_suggestion_covers_the_line_it_rewrites_above_and_applied_it_works(apply, provider):
    comment = _post({"line": 35, "suggestion": LIVE_SUGGESTION}, provider)
    assert (comment.start_line, comment.line) == (34, 35)
    applied = apply(comment)
    assert "    percent = COUPONS[code]" not in applied and "    return amount - amount * percent / 100" not in applied
    apply_coupon = _coupon(applied)
    assert apply_coupon(100.0, " welcome10 ") == 90.0
    with pytest.raises(ValueError, match="unknown coupon code"):
        apply_coupon(100.0, "NOPE")


def test_a_suggestion_that_rewrites_the_line_below_its_range_covers_it_too():
    comment = _post({"line": 34, "suggestion": LIVE_SUGGESTION}, "gitlab")
    assert (comment.start_line, comment.line) == (34, 35)
    assert _coupon(_apply_gitlab(comment))(50.0, "SPRING25") == 37.5


def test_a_suggestion_of_exactly_its_line_keeps_its_range():
    comment = _post({"line": 35, "suggestion": "    return round(amount - amount * percent / 100, 2)"}, "gitlab")
    assert (comment.start_line, comment.line) == (0, 35)
    assert "suggestion:-0+0" in comment.body


def test_an_inserted_guard_does_not_swallow_its_neighbours():
    files = parse_diff(DIFF)
    suggestion = "    if code not in COUPONS:\n        raise ValueError(code)\n    percent = COUPONS[code]"
    assert cover(files, "shop/pricing.py", 34, 34, suggestion) == (34, 34)


def test_a_suggestion_that_rewrites_nothing_of_its_range_is_left_as_given():
    files = parse_diff(DIFF)
    assert cover(files, "shop/pricing.py", 35, 35, "    log.info('coupon applied')") == (35, 35)
