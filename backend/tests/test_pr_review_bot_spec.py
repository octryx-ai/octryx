"""PR review bot: the specification for the reviewer.

- the repository's SPEC.md of the changed app: only its sections that name the change (never its Decisions section,
  which the platform checks itself), bounded, fenced as data;
- Confluence pages the ticket links: read through the governed tool, only the parts that name the change; a
  confidential Workspace reads only pages of its own spaces and names what it left out;
- the footer says which specification the review had.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.models import WorkflowRun, WorkItem
from app.services.pr_review_bot import spec_context
from app.services.pr_review_bot.events import pull_request_event
from app.services.pr_review_bot.render import build_post
from app.services.pr_review_bot.starter import TRIGGER_WEBHOOK, start_review
from app.services.workflow_runs.review.runner import run_due_reviews
from tests.pr_review_bot_flow_support import HEADERS, REVIEW, _payload, _tools, _workspace
from tests.workflow_run_review_support import ScriptedReviewer

SPEC = """# Pay

Intro about the shop.

## Totals

The total function rounds half up; see totals.py.

## Invoices

Invoices are due after 30 days.

## Decisions

- Rounding: half up (`total`)
"""


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def test_only_the_spec_sections_that_name_the_change_never_its_decisions():
    names = spec_context.terms(["pay/totals.py"], "+def total(items):\n+    return 1\n")
    assert {"totals", "total"} <= names
    text = spec_context.relevant(spec_context.sections(SPEC), names, 3, 8000)
    assert "rounds half up; see totals.py" in text and "Invoices are due" not in text and "Rounding: half up" not in text
    assert spec_context.relevant(spec_context.sections(SPEC), {"nothing"}, 3, 8000) == ""
    assert len(spec_context.relevant(spec_context.sections(SPEC * 50), names, 3, 100)) <= 100


def test_confluence_links_and_page_bodies_are_read_as_sections():
    description = ("Spec: https://acme.atlassian.net/wiki/spaces/PAY/pages/12345/Totals and "
                   "https://wiki.acme.test/pages/viewpage.action?pageId=777 (twice: …pages/12345/x)")
    assert spec_context.page_ids(description) == ["12345", "777"]
    parts = spec_context.page_text("<h2>Totals</h2><p>The <b>total</b> rounds half up &amp; is in CHF.</p>")
    assert parts[-1][0] == "Totals" and "rounds half up & is in CHF" in parts[-1][1]


async def _run_with_ticket(db, description: str) -> WorkflowRun:
    project_id, _record, _hook = await _workspace(db)
    item = WorkItem(source_type="platform", source_instance="octryx", source_key="PAY-1", source_project_key="PAY",
                    title="Totals", description=description, project_id=project_id, work_state="development")
    db.add(item)
    await db.flush()
    run = WorkflowRun(project_id=project_id, workflow_kind="phased", workflow_key="pr-review-bot", title="bot",
                      requested_by="bot", repository="github:acme/pay", branch="feature/PAY-1", work_item_id=item.id,
                      context={"pr_review": {}})
    db.add(run)
    await db.flush()
    return run


async def test_a_confidential_workspace_reads_only_its_own_spaces(db, monkeypatch):
    run = await _run_with_ticket(db, "https://acme.atlassian.net/wiki/spaces/PAY/pages/1/x "
                                     "https://acme.atlassian.net/wiki/spaces/HR/pages/2/y")
    pages = {"1": {"id": "1", "title": "Pay spec", "space_key": "PAY", "url": "https://acme/1",
                   "content": "<h2>Totals</h2><p>total rounds half up</p>"},
             "2": {"id": "2", "title": "HR spec", "space_key": "HR", "content": "<p>total salaries</p>"}}
    asked = []

    async def dispatch(_db, _run, tool, arguments, *, capability_class, **_):
        from app.services.workflow_runs.platform.dispatch import SUCCEEDED, ToolOutcome

        asked.append((tool, arguments["page_id"], capability_class))
        return ToolOutcome(SUCCEEDED, pages[arguments["page_id"]])

    async def confidential(_db, _project_id):
        return True

    async def own(_db, _project_id):
        return {"PAY"}

    monkeypatch.setattr("app.services.workflow_runs.platform.dispatch.dispatch_tool", dispatch)
    monkeypatch.setattr(spec_context, "_confidential", confidential)
    monkeypatch.setattr(spec_context, "_own_spaces", own)
    found, notes = await spec_context.confluence_pages(db, run, {"total", "totals"})
    assert [page["page"]["id"] for page in found] == ["1"] and "total rounds half up" in found[0]["text"]
    assert notes == ["Confluence page 2 left out: space HR is not this confidential Workspace's own"]
    assert asked == [("get_confluence_page", "1", "read_only"), ("get_confluence_page", "2", "read_only")]

    async def open_level(_db, _project_id):
        return False

    monkeypatch.setattr(spec_context, "_confidential", open_level)
    found, notes = await spec_context.confluence_pages(db, run, {"total"})
    assert [page["page"]["id"] for page in found] == ["1", "2"] and notes == []


def test_the_footer_names_the_specification():
    post = build_post({"verdict": "pass", "summary": "", "findings": []}, {}, provider="github", facts={
        "sha": "a" * 40, "spec": {"path": "SPEC.md", "pages": [{"title": "Pay spec"}],
                                  "notes": ["Confluence page 2 left out: space HR is not this confidential …"]}})
    assert "spec `SPEC.md`, Confluence 'Pay spec'" in post.summary and "page 2 left out" in post.summary


async def test_the_bot_gives_the_reviewer_the_spec_sections_of_the_change(db, monkeypatch, tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    (origin / "SPEC.md").write_text(SPEC)
    (origin / "totals.py").write_text("def total(items):\n    return int(sum(items))\n")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-qm", "init")
    _git(origin, "checkout", "-q", "-b", "feature/PAY-1-totals")
    (origin / "totals.py").write_text("def total(items):\n    return round(sum(items))\n")
    _git(origin, "commit", "-qam", "round")
    head = _git(origin, "rev-parse", "HEAD")
    _git(origin, "checkout", "-q", "main")
    _git(tmp_path, "clone", "-q", str(origin), str(tmp_path / "pay"))
    tools = _tools(monkeypatch, Path(tmp_path / "pay"))
    project_id, _record, _hook = await _workspace(db)
    await start_review(db, project_id, pull_request_event(_payload(head), HEADERS), trigger=TRIGGER_WEBHOOK)
    reviewer = ScriptedReviewer(REVIEW)
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    task = reviewer.tasks[0][1]
    assert "<<<specification SPEC.md the sections this change touches" in task  # fenced as data
    assert "The total function rounds half up" in task and "Invoices are due" not in task
    posted = [call[1] for call in tools.calls if call[0] == "post_github_pull_request_review"][-1]
    assert "spec `SPEC.md`" in posted["summary"]
