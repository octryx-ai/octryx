"""PR review bot, the code graph and the acceptance table on incremental passes.

- the code graph's callers and references of the changed symbols (any indexed language) reach the reviewer as
  context, outside the changed files, bounded; an unindexed repository changes nothing;
- a pull request an Octryx run opened gets that run's confirmed criteria and test facts;
- an incremental pass keeps the previous acceptance rows (a follow-up commit never looks worse) and asks again
  only for what is not covered, or covered by a file the delta changes.
"""

from __future__ import annotations

from app.models import WorkflowRun
from app.services.pr_review_bot import graph_context, ticket_context
from app.services.workflow_runs.review.convergence import Scope, previous_findings, settle_follow_up
from tests.pr_review_bot_flow_support import _workspace

DIFF = """diff --git a/pay/totals.py b/pay/totals.py
--- a/pay/totals.py
+++ b/pay/totals.py
-def vat(amount):
+def vat(amount, rate):
+    return amount * rate
diff --git a/web/cart.ts b/web/cart.ts
+export async function cartTotal(items: Item[]): number {
+    const self = 1
+    return round_money(total)
+  public static int Count(List<Item> items) {
"""


def test_the_changed_symbols_of_any_language():
    assert graph_context.changed_symbols(DIFF) == ["vat", "cartTotal", "Count"]  # a call is no definition


def test_callers_outside_the_change_are_listed_per_symbol():
    impacts = {"vat": {"risk": "medium", "callers": [
        {"path": "pay/report.py", "line": 5, "text": "return vat(net)"},
        {"path": "pay/totals.py", "line": 9}],  # inside the change: the diff shows it already
        "references": [{"path": "pay/report.py", "line": 5}, {"path": "web/invoice.ts", "line": 12, "name": "vat"}]}}
    text, count, files = graph_context.graph_text(impacts, {"pay/totals.py"})
    assert text.splitlines() == ["vat (risk medium): used outside this change at", "  pay/report.py:5 return vat(net)",
                                 "  web/invoice.ts:12 vat"]
    assert (count, files) == (2, {"pay/report.py", "web/invoice.ts"})


async def test_the_code_graph_adds_context_or_nothing_when_the_repository_is_not_indexed(db, monkeypatch, tmp_path):
    import subprocess

    project_id, record, _hook = await _workspace(db)
    root = tmp_path / "repo"
    root.mkdir()
    for args in (["init", "-q", "-b", "main"],):
        subprocess.run(["git", *args], cwd=root, check=True)
    (root / "totals.py").write_text("def vat(amount):\n    return amount\n")
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "a"], cwd=root, check=True)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    (root / "totals.py").write_text("def vat(amount, rate):\n    return amount * rate\n")
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "b"], cwd=root, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    run = WorkflowRun(project_id=project_id, workflow_kind="phased", workflow_key="pr-review-bot", title="bot",
                      requested_by="bot", repository="github:acme/pay", branch="f", context={})
    asked = []

    async def impact(*, db, repository_id, cwd, project_id, symbol, limit):
        asked.append((repository_id, symbol))
        return {"risk": "low", "callers": [{"path": "report.py", "line": 3, "text": "vat(net)"}]}

    monkeypatch.setattr("app.services.code_intelligence.queries.build_impact_analysis", impact)
    facts = await graph_context.code_graph(db, run, str(root), base, head)
    assert asked == [(record.id, "vat")] and facts == {"symbols": 1, "callers": 1, "files": 1}
    assert run.context["review_context_sections"][0]["text"].endswith("report.py:3 vat(net)")

    async def unindexed(**_kwargs):
        raise RuntimeError("repository not indexed")

    monkeypatch.setattr("app.services.code_intelligence.queries.build_impact_analysis", unindexed)
    plain = WorkflowRun(project_id=project_id, repository="github:acme/pay", context={})
    assert await graph_context.code_graph(db, plain, str(root), base, head) == {"unavailable": True}
    assert "review_context_sections" not in plain.context


async def test_an_agent_pull_request_carries_its_runs_confirmed_tests(db):
    project_id, _record, _hook = await _workspace(db)
    author = WorkflowRun(project_id=project_id, workflow_kind="phased", workflow_key="story-delivery", title="s",
                         requested_by="u", context={"confirmed_tests": ["tests/test_pay.py::test_rounds"]})
    run = WorkflowRun(project_id=project_id, workflow_kind="phased", workflow_key="pr-review-bot", title="bot",
                      requested_by="bot", context={})
    db.add_all([author, run])
    await db.flush()
    assert (await graph_context.authoring_run(db, run, author.id))["run"] == author.id
    section = run.context["review_context_sections"][0]
    assert section["title"].startswith(f"the Octryx run {author.id[:8]} that opened this pull request")
    assert "tests/test_pay.py::test_rounds" in section["text"]


CRITERIA = [{"id": "AC1", "text": "returns subtotal minus total"}, {"id": "AC2", "text": "an empty order saves 0"},
            {"id": "AC3", "text": "rounded to 2 decimal places"}]
PREVIOUS = [{"criterion": "AC1: returns subtotal minus total", "status": "covered", "evidence": "pay/savings.py:17"},
            {"criterion": "AC2: an empty order saves 0", "status": "covered", "evidence": "tests/test_pay.py:40"},
            {"criterion": "AC3: rounded to 2 decimal places", "status": "missing", "evidence": "no rounding"}]


def test_an_incremental_pass_asks_again_only_what_may_have_changed():
    asked = ticket_context.to_reassess(CRITERIA, PREVIOUS, {"pay/savings.py"})
    assert [(item["id"], item.get("recheck", False)) for item in asked] == [("AC1", True), ("AC3", False)]
    assert ticket_context.to_reassess(CRITERIA, PREVIOUS, {"README.md"}) == [CRITERIA[2]]


def test_unanswered_criteria_keep_their_previous_row_never_turn_into_not_assessed():
    criteria = [{**CRITERIA[0], "recheck": True}, CRITERIA[1], CRITERIA[2]]
    rows = ticket_context.acceptance_rows(criteria, [
        {"criterion": "AC3", "status": "covered", "evidence": "pay/savings.py:17 round_money"}], PREVIOUS)
    assert [(row["criterion"][:3], row["status"]) for row in rows] == [
        ("AC1", "covered"), ("AC2", "covered"), ("AC3", "covered")]
    assert rows[0]["evidence"] == "pay/savings.py:17 (not re-checked after the change)"
    assert rows[1]["evidence"] == "tests/test_pay.py:40"


def test_a_follow_up_answer_keeps_its_acceptance_rows():
    from app.services.pr_review_bot.incremental import seed

    open_findings = [{"id": "F1", "severity": "high", "file": "pay/savings.py", "line": 17, "fix": "Round it."}]
    run = type("Run", (), {"context": {"review": seed({"open_findings": open_findings})}})()
    previous = previous_findings(run, type("Node", (), {"id": "independent_review"})())
    settled = settle_follow_up({"summary": "F1 fixed.", "previous": [{"id": "F1", "status": "fixed"}],
                                "findings": [], "acceptance": [{"criterion": "AC3", "status": "covered",
                                                                "evidence": "pay/savings.py:17"}]},
                               previous, Scope(("pay/savings.py",), ()))
    assert settled.record()["acceptance"] == [{"criterion": "AC3", "status": "covered",
                                               "evidence": "pay/savings.py:17"}]


async def test_the_definitions_of_called_functions_outside_the_change_are_shown(tmp_path):
    """round_money lives in pay/money.py; the diff shows only its call, so without the graph the reviewer judges
    the rounding criterion "partial"."""
    import subprocess

    root = tmp_path / "repo"
    (root / "pay").mkdir(parents=True)
    (root / "pay/money.py").write_text(
        "from decimal import ROUND_HALF_UP, Decimal\n\n\ndef round_money(amount: Decimal) -> Decimal:\n"
        "    return amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)\n\n\ndef other():\n    return 1\n")
    (root / "pay/savings.py").write_text("x = 1\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    diff = ("+++ b/pay/savings.py\n+def bulk_savings(prices):\n"
            "+    return round_money(subtotal(prices) * BULK_PERCENT / Decimal(\"100\"))\n")
    assert graph_context.called_names(diff) == ["round_money", "subtotal"]  # Decimal and its own def are not
    found = await graph_context.callee_definitions(str(root), ["round_money", "subtotal"], {"pay/savings.py"})
    assert [(name, where) for name, where, _code in found] == [("round_money", "pay/money.py:4")]
    assert found[0][2].splitlines() == ["def round_money(amount: Decimal) -> Decimal:",
                                        "    return amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)"]
