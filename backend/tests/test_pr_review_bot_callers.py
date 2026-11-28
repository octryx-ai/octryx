"""PR review bot, calls outside the diff."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.services.pr_review_bot.actions import with_caller_findings
from app.services.pr_review_bot.callers import check_callers
from app.services.pr_review_bot.signatures import call_problem, changed_signatures, public_callables

TOTALS = '''from decimal import Decimal

VAT_RATE = Decimal("0.081")


def vat(amount):
    return amount * VAT_RATE


class Invoice:
    def __init__(self, number):
        self.number = number

    def total(self, prices):
        return sum(prices)
'''
REPORT = '''from .totals import vat


def order_summary(net):
    tax = vat(net)
    return f"Net {net}, VAT {tax}"
'''
OTHER = '''import pay.totals as t
from pay.totals import Invoice as Bill


def vat(amount, rate, extra):  # another module's own vat: never judged against pay.totals
    return 0


def run():
    t.vat(1)
    vat(1, 2, 3)
    Bill(7).total([1])
'''


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def _repo(tmp_path: Path, totals_head: str, extra: dict[str, str] | None = None) -> tuple[str, str]:
    repo = tmp_path / "repo"
    (repo / "pay").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    files = {"pay/__init__.py": "", "pay/totals.py": TOTALS, "pay/report.py": REPORT, "pay/other.py": OTHER}
    for path, text in files.items():
        (repo / path).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "pay/totals.py").write_text(totals_head)
    for path, text in (extra or {}).items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "head")
    return str(repo), base


async def test_a_new_required_parameter_breaks_the_calls_outside_the_diff(tmp_path):
    root, base = _repo(tmp_path, TOTALS.replace("def vat(amount):", "def vat(amount, rate):"))
    checked = await check_callers(root, base)
    assert sorted((item["file"], item["line"], item["severity"]) for item in checked.findings) == [
        ("pay/other.py", 10, "high"), ("pay/report.py", 5, "high")]
    report = next(item for item in checked.findings if item["file"] == "pay/report.py")
    assert "`vat(amount)` became `vat(amount, rate)` in pay/totals.py" in report["fix"]
    assert "misses the required argument 'rate'" in report["fix"]
    # pay/other.py's own vat(1, 2, 3) is another function: never a finding.
    assert all(item["line"] != 11 for item in checked.findings if item["file"] == "pay/other.py")
    assert checked.changes == ["pay/totals.py: vat(amount) -> vat(amount, rate)"]


async def test_a_new_parameter_with_a_default_is_compatible_and_its_calls_are_context(tmp_path):
    root, base = _repo(tmp_path, TOTALS.replace("def vat(amount):", "def vat(amount, rate=VAT_RATE):"))
    checked = await check_callers(root, base)
    assert checked.findings == []
    assert any(line.startswith("pay/report.py:5: tax = vat(net)") for line in checked.fitting)
    assert "Calls outside the diff that still fit" in checked.context()


async def test_a_removed_method_and_a_changed_constructor_are_found_through_their_class(tmp_path):
    head = TOTALS.replace("def __init__(self, number):", "def __init__(self, number, currency):").replace(
        "    def total(self, prices):\n        return sum(prices)\n", "")
    root, base = _repo(tmp_path, head)
    fixes = [item["fix"] for item in (await check_callers(root, base)).findings
             if (item["file"], item["line"]) == ("pay/other.py", 12)]
    assert any("misses the required argument 'currency'" in fix for fix in fixes)
    assert any("Invoice.total" in fix and "was removed" in fix for fix in fixes)


async def test_other_languages_are_named_as_not_checked(tmp_path):
    root, base = _repo(tmp_path, TOTALS, extra={"web/app.ts": "export const x = 1;\n"})
    assert (await check_callers(root, base)).not_checked == [".ts"]


def test_a_call_with_star_arguments_cannot_be_judged_and_counts_as_fitting():
    import ast

    signature = public_callables("def vat(amount, rate): pass\n")["vat"]
    assert call_problem(ast.parse("vat(*args)").body[0].value, signature) == ""
    assert call_problem(ast.parse("vat(1, rate=2)").body[0].value, signature) == ""
    assert "twice" in call_problem(ast.parse("vat(1, amount=2)").body[0].value, signature)
    assert changed_signatures("def f(:\n", "def f(): pass\n") == []


def test_a_broken_call_turns_a_passed_review_into_changes():
    finding = {"severity": "high", "file": "pay/report.py", "line": 5, "fix": "...", "id": "C1"}
    passed = {"verdict": "pass", "summary": "Looks good.", "findings": []}
    assert with_caller_findings(passed, [finding])["verdict"] == "changes"
    already = {"verdict": "changes", "summary": "x", "findings": [{**finding, "id": "F1"}]}
    assert with_caller_findings(already, [finding]) == already


def test_the_reviewers_context_sections_are_fenced_bounded_and_say_what_they_leave_out():
    from app.models import WorkflowRun
    from app.services.workflow_runs.review import evidence

    run = WorkflowRun(context={"review_context_sections": [
        {"title": f"s{index}", "text": "x" * (evidence.MAX_CONTEXT_CHARS + 5)} for index in range(12)]})
    sections = evidence.context_sections(run, "FENCE")
    assert len(sections) == evidence.MAX_CONTEXT_SECTIONS
    assert all("FENCE" in section and "[5 more characters not shown]" in section for section in sections)
    assert evidence.context_sections(WorkflowRun(context={}), "FENCE") == []
