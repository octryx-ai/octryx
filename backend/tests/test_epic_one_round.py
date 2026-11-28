"""One question round per epic, a design system, and a reviewer that sees the screens."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from app.models.runtime.secure_work import WorkItem
from app.services.workflow_runs.auto_accept import accept_reason
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.review import screens
from app.services.workflow_runs.review.model import user_content
from app.services.workflow_runs.review.reviewer_agent import ReviewerSetup, order_review_runtimes
from tests.phased_workflow_fixtures import PHASE, admin_user, phase_turn, publish_phased, run_workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def test_a_spec_run_without_a_task_list_passes_on_the_review_alone():
    run = SimpleNamespace(context={"review": {"verdict": "pass", "findings": [{"severity": "low"}]}})
    assert accept_reason(run, needs_tasks=False) != ""
    assert accept_reason(run) == ""  # a story still needs every task verified
    run.context["review"]["findings"] = [{"severity": "medium"}]
    assert accept_reason(run, needs_tasks=False) == ""


def test_the_review_nodes_model_goes_first_also_when_the_author_used_it():
    gemma = {"model": "gemma-4-31b", "use_case_tags": ["coding"]}
    haiku = {"model": "claude-haiku-5-5", "use_case_tags": []}
    setup = ReviewerSetup(definition_id="r", instructions="", runtime_preference="coding",
                          author_model="claude-haiku-5-5")
    assert order_review_runtimes([gemma, haiku], setup) == ([gemma, haiku], False)
    assert order_review_runtimes([gemma, haiku], setup, model="claude-haiku-5-5") == ([haiku, gemma], True)
    assert order_review_runtimes([gemma], setup, model="claude-haiku-5-5") == ([gemma], False)


def test_screenshots_are_kept_per_pass_outside_the_tree_and_shown_with_their_names(tmp_path):
    (tmp_path / ".git").mkdir()
    run = SimpleNamespace(context={"local_path": str(tmp_path)})
    assert screens.store(run, node_id="implement", entry=1, name="../home.png", data=PNG) == ""
    assert screens.store(run, node_id="implement", entry=1, name="x.png", data=b"<svg/>") == "not_an_image"
    assert [s.name for s in screens.collect(run, "implement")] == ["home.png"]
    assert (tmp_path / ".git" / "octryx-screens" / "implement" / "home.png").is_file()
    screens.store(run, node_id="implement", entry=2, name="plan.png", data=PNG)  # a new pass drops the old screens
    assert [s.name for s in screens.collect(run, "implement")] == ["plan.png"]
    content = user_content("review this", screens.collect(run, "implement"))
    assert content[1] == {"type": "text", "text": "Screenshot: plan.png"}
    assert content[2]["image_url"]["url"].startswith("data:image/png;base64,")
    assert user_content("text only", []) == "text only"


def test_a_server_run_reviews_its_system_test_screenshots(tmp_path):
    (tmp_path / ".git").mkdir()
    folder = tmp_path / "test-reports" / "screenshots"
    folder.mkdir(parents=True)
    (folder / "cook.png").write_bytes(PNG)
    (folder / "notes.txt").write_text("no image")
    run = SimpleNamespace(context={"local_path": str(tmp_path)})
    assert [s.name for s in screens.collect(run, "implement")] == ["cook.png"]


def _definition(auto: dict) -> dict:
    return {
        "execution_kind": "phased",
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "work", "type": "phase", "label": "Work", "config": copy.deepcopy(PHASE)},
            {"id": "ready", "type": "user_confirmation", "label": "Ready", "config": {"subject": "readiness", **auto}},
            {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
            {"id": "stopped", "type": "outcome", "config": {"outcome": "stopped"}},
        ],
        "edges": [
            {"id": "a", "source_node_id": "start", "target_node_id": "work"},
            {"id": "b", "source_node_id": "work", "target_node_id": "ready"},
            {"id": "c", "source_node_id": "ready", "target_node_id": "done", "when": "confirmed"},
            {"id": "d", "source_node_id": "ready", "target_node_id": "stopped", "when": "stopped"},
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("epic, waits", [("OCX-1", False), (None, True)])
async def test_a_story_of_an_epic_takes_the_readiness_proposals_without_asking(db, epic, waits):
    admin = await admin_user(db)
    item = WorkItem(source_type="platform", source_instance="octryx", source_key="OCX-2", title="S1", epic_key=epic,
                    work_state="intake")
    db.add(item)
    await db.flush()
    key = await publish_phased(db, _definition({"auto_accept": "epic_story"}))
    workspace_id = await run_workspace(db, admin, item.id)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=key,
                          project_id=workspace_id, session=session, work_item_id=item.id)
    resolution = await run_turn_resolution(db, session, user_message="Check it.")
    await phase_turn(db, session.id, resolution, ["knowledge_search"])
    if waits:
        assert run.waiting_kind == "awaiting_confirmation"
        return
    assert run.status == "completed" and run.waiting_kind is None
    answer = run.context["po_answers"][-1]
    assert "epic OCX-1" in answer["text"] and answer["by"] is None


@pytest.mark.asyncio
async def test_review_findings_go_back_to_the_agent_twice_before_the_product_owner_is_asked(db, tmp_path):
    from app.services.workflow_runs.review.runner import run_due_reviews
    from tests.test_ticket_delivery import _definition as delivery
    from tests.test_workflow_run_pause import _turn
    from tests.workflow_run_review_support import ScriptedReviewer, changed_repo

    definition = delivery()
    definition["nodes"].insert(2, {"id": "review", "type": "review", "label": "Review", "config": {"phase": "work"}})
    definition["nodes"][3]["config"].update({"shows": "review_verdict", "auto_accept": "review_passed",
                                             "auto_revise": 2})
    definition["edges"][1] = {"id": "b", "source_node_id": "work", "target_node_id": "review"}
    definition["edges"].append({"id": "f", "source_node_id": "review", "target_node_id": "decisions"})
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    session.metadata_ = {**dict(session.metadata_ or {}), "workspace_root": str(changed_repo(tmp_path / "w"))}
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition),
                          project_id=workspace_id, session=session)
    await db.commit()
    changes = {"verdict": "changes", "summary": "No.", "findings": [
        {"severity": "medium", "fix": "Shopping list is missing from the navigation"}]}
    reviewer = ScriptedReviewer(changes, changes, changes)
    for revision in (1, 2):
        await _turn(db, session.id, ["knowledge_search"])
        assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
        await db.refresh(run)
        assert run.current_node_id == "work" and run.context["auto_revisions"] == {"decisions": revision}
        assert f"Automatic revision {revision} of 2" in run.context["po_answers"][-1]["text"]
    await _turn(db, session.id, ["knowledge_search"])
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    await db.refresh(run)
    assert run.node_state["waiting"]["subject"] == "decisions"  # the third time the product owner decides
    # Follow-up reviews see their previous findings and report only what is still open or newly broken.
    from app.services.workflow_runs.review.convergence import FOLLOW_UP_RULE

    assert FOLLOW_UP_RULE not in reviewer.tasks[0][0] and FOLLOW_UP_RULE in reviewer.tasks[1][0]
    assert "Shopping list is missing from the navigation" in reviewer.tasks[1][1]


@pytest.mark.asyncio
async def test_the_chosen_review_model_rides_on_a_provider_the_workspace_routes_to(db):
    import uuid

    from app.models import LLMModel, LLMProvider
    from app.services.workflow_runs.review.model import _chosen_model_runtimes

    provider = LLMProvider(id=str(uuid.uuid4()), name="gw", display_name="Gateway", is_global=True, is_active=True)
    db.add(provider)
    await db.flush()
    db.add_all([LLMModel(id=str(uuid.uuid4()), provider_id=provider.id, model_id="claude-haiku-5-5", is_active=True,
                         supports_vision=True, pricing_input=0.1, pricing_output=0.5),
                LLMModel(id=str(uuid.uuid4()), provider_id=provider.id, model_id="claude-opus-5-5", is_active=False)])
    await db.flush()
    gemma = {"provider_id": provider.id, "model": "gemma-4-31b", "use_case_tags": ["coding"], "base_url": "x"}
    [haiku] = await _chosen_model_runtimes(db, [gemma], "claude-haiku-5-5")
    assert (haiku["model"], haiku["base_url"], haiku["supports_vision"], haiku["use_case_tags"]) == (
        "claude-haiku-5-5", "x", True, [])
    assert await _chosen_model_runtimes(db, [gemma], "claude-opus-5-5") == []


def test_a_long_review_stays_a_verdict_and_nothing_in_it_is_cut():
    from app.services.workflow_runs.review.model import answer_tokens
    from app.services.workflow_runs.review.verdict import parse_verdict

    fix = "T7: " + "the shopping list is missing from the navigation; " * 40
    verdict = parse_verdict({"verdict": "changes", "summary": "s" * 2000, "assumptions": ["a" * 900] * 25,
                             "findings": [{"severity": "medium", "file": "x.js", "line": 1, "fix": fix}] * 45})
    assert verdict is not None and len(verdict.findings) == 45 and verdict.findings[0].fix == fix.strip()
    assert len(verdict.summary) == 2000 and len(verdict.assumptions) == 25
    assert answer_tokens({"max_tokens_per_request": 128000}) == 128000 and answer_tokens({}) == 64000


@pytest.mark.asyncio
async def test_more_screenshots_than_a_request_takes_are_looked_at_in_batches():
    from app.services.workflow_runs.review.model import ReviewAnswer, ReviewUsage
    from app.services.workflow_runs.review.reading import IMAGES_PER_REQUEST, _answer_with_screens

    calls = []

    class Model:
        async def answer(self, *, system, user, images=None):
            calls.append((system, user, [screen.name for screen in images or []]))
            if images:
                return ReviewAnswer({"audit": [{"screenshot": images[0].name, "severity": "medium",
                                                "problem": "shopping list missing from the navigation"}]},
                                    ReviewUsage(model="m", tokens_in=10, tokens_out=1))
            return ReviewAnswer({"verdict": "pass", "summary": "ok", "findings": []},
                                ReviewUsage(model="m", tokens_in=5, tokens_out=1))

    shots = [screens.Screen(f"s{n:02}.png", "image/png", PNG) for n in range(32)]
    answered = await _answer_with_screens(Model(), "sys", "task with the diff", shots, "lean task")
    assert [len(names) for _s, _u, names in calls] == [IMAGES_PER_REQUEST, 12, 0]
    assert sorted(sum((names for _s, _u, names in calls), [])) == [shot.name for shot in shots]
    assert calls[0][1] == calls[1][1]  # the same text for every batch (cache)
    assert calls[0][1].startswith("lean task") and "diff" not in calls[0][1]  # no change in it (price tier)
    assert calls[2][1].startswith("task with the diff")
    assert "s00.png" in calls[2][1] and "s20.png" in calls[2][1] and "All 32 screenshots" in calls[2][1]
    assert answered.answer["verdict"] == "pass" and answered.usage.tokens_in == 25
    calls.clear()
    await _answer_with_screens(Model(), "sys", "task", shots[:5], "lean task")
    assert [len(names) for _s, _u, names in calls] == [5, 0]


def test_the_screens_task_carries_the_specs_ui_and_design_sections_whole(tmp_path):
    from app.services.workflow_runs.review.evidence import design_sections

    (tmp_path / "benchmark").mkdir()
    (tmp_path / "benchmark" / "SPEC.md").write_text(
        "# benchmark\n## 4 Rules\nranking...\n## 8 UI and Design\n### 8.1 Design tokens\nAccent #E67E22\n"
        "### 8.3 App shell and navigation map\nEvery screen in the nav.\n## 9 Decisions\nD1\n")
    text = design_sections(tmp_path)
    assert "Accent #E67E22" in text and "Every screen in the nav." in text
    assert "ranking" not in text and "D1" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("severity, accepted", [("medium", True), ("high", False)])
async def test_a_spec_revised_twice_without_a_high_finding_is_accepted(db, tmp_path, severity, accepted):
    from app.services.workflow_runs.review.runner import run_due_reviews
    from tests.test_ticket_delivery import _definition as delivery
    from tests.test_workflow_run_pause import _turn
    from tests.workflow_run_review_support import ScriptedReviewer, changed_repo

    definition = delivery()
    definition["nodes"].insert(2, {"id": "review", "type": "review", "label": "Review", "config": {"phase": "work"}})
    definition["nodes"][3]["config"].update({"shows": "review_verdict", "auto_accept": "review_passed",
                                             "auto_revise": 2, "tasks": False, "accept_after_revisions": True})
    definition["edges"][1] = {"id": "b", "source_node_id": "work", "target_node_id": "review"}
    definition["edges"].append({"id": "f", "source_node_id": "review", "target_node_id": "decisions"})
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    session.metadata_ = {**dict(session.metadata_ or {}), "workspace_root": str(changed_repo(tmp_path / "w"))}
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition),
                          project_id=workspace_id, session=session)
    await db.commit()
    changes = {"verdict": "changes", "summary": "No.", "findings": [{"severity": severity, "fix": "State the default"}]}
    reviewer = ScriptedReviewer(changes, changes, changes)
    for _ in range(3):
        await _turn(db, session.id, ["knowledge_search"])
        assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
        await db.refresh(run)
    assert (run.status == "completed") is accepted
    assert (run.node_state.get("waiting", {}).get("subject") == "decisions") is not accepted


def test_a_product_owners_answer_starts_a_new_round_of_automatic_revisions():
    from types import SimpleNamespace

    from app.services.workflow_runs.po_answers import _record_po_answer

    run = SimpleNamespace(context={"review": {"attempt": "a"}, "auto_revisions": {"decisions": 2}})
    _record_po_answer(run, "Fix the eight findings.", user_id="u")
    assert run.context["auto_revisions"] == {} and run.context["po_answers"][-1]["text"] == "Fix the eight findings."
