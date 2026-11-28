"""What the workflow builds should look like the product the spec describes; a visibly incomplete page must not pass
as a low note through the automatic accept."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.workflow_runs.review import screens
from app.services.workflow_runs.review.model import ReviewAnswer, ReviewUsage
from tests.phased_seed_definitions import seed_definitions
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
SEEDS = Path(__file__).resolve().parents[1] / "app/services/workflow_runs/seeds/phased_workflows.json"


def _contract(key: str, node: str) -> str:
    seed = next(item for item in seed_definitions() if item["key"] == key)
    config = next(item for item in seed["definition"]["nodes"] if item["id"] == node)["config"]
    return config["workflow_contract"]["when_to_use"]


def test_the_spec_draws_its_visual_anchors_and_ends_the_design_with_a_look_and_feel_list():
    from app.services.workflow_runs.review.verdict import SPEC_REVIEW_RULE

    interview, draft = _contract("spec-writing", "interview"), _contract("spec-writing", "draft")
    assert "visual signature" in interview
    assert "described as drawn" in draft and "colour stops" in draft and "neighbouring items differ" in draft
    assert '"Look and feel" list' in draft and "LF1" in draft
    assert "bottom of the viewport" in draft and "empty region" in draft and "screen's language" in draft
    assert '"a coloured area"' in SPEC_REVIEW_RULE and "Look and feel" in SPEC_REVIEW_RULE


def test_the_build_screenshots_every_state_after_interaction_and_checks_it_against_the_look():
    from app.services.workflow_runs.octryx.system_tests import rule_text

    RULE = rule_text("python -m pytest -v tests/system")  # noqa: N806

    assert "after each interaction" in RULE and "'<screen>-<state>.png'" in RULE
    assert "the line items under 'Your cart'" in RULE and "Look and feel" in RULE


def test_a_look_and_feel_list_under_its_own_heading_reaches_the_screen_review(tmp_path):
    from app.services.workflow_runs.review.evidence import design_sections

    (tmp_path / "SPEC.md").write_text(
        "# benchmark\n## 4 Rules\nranking\n## 8 UI and Design\nwarm\n## 9 Look and feel\n"
        "LF1 Search: dish cards show a warm gradient with the dish icon.\n## 10 Decisions\nD1\n")
    text = design_sections(tmp_path)
    assert "LF1 Search" in text and "ranking" not in text and "D1" not in text


def test_a_missed_look_check_that_the_verdict_drops_comes_back_as_a_high_finding():
    from app.services.workflow_runs.review.answer_checks import look_floor

    passed = {"verdict": "pass", "summary": "Looks fine.", "findings": []}
    note = {"screenshot": "search-results.png", "check": "LF2", "severity": "high",
            "problem": "flat peach blocks, the spec draws a gradient with the dish icon"}
    floored = look_floor(passed, [note])
    assert floored["verdict"] == "changes"
    assert floored["findings"] == [{"severity": "high", "file": "search-results.png", "line": 1,
                                    "fix": "LF2, search-results.png: flat peach blocks, the spec draws a gradient "
                                           "with the dish icon"}]
    carried = {"verdict": "changes", "summary": "s", "findings": [
        {"severity": "high", "file": "web/cards.css", "line": 4, "fix": "LF2: draw the gradient"}]}
    explained = {**passed, "summary": "search-results.png shows the loading state, LF2 does not apply there."}
    assert look_floor(carried, [note]) == carried and look_floor(explained, [note]) == explained
    assert look_floor(passed, [{**note, "severity": "medium"}, {**note, "check": "layout"}]) == passed


@pytest.mark.asyncio
async def test_every_screenshot_batch_knows_all_screenshot_names():
    from app.services.workflow_runs.review.reading import NOTES_KEY, _answer_with_screens

    seen = []

    class Model:
        async def answer(self, *, system, user, images=None):
            seen.append((user, bool(images)))
            if images:
                return ReviewAnswer({"audit": [{"screenshot": images[0].name, "check": "content", "severity": "high",
                                                "problem": "Ingredients heading above nothing"}]}, ReviewUsage())
            return ReviewAnswer({"verdict": "pass", "summary": "ok", "findings": []}, ReviewUsage())

    shots = [screens.Screen(f"s{n:02}.png", "image/png", PNG) for n in range(21)] + [
        screens.Screen("cook-mode-open.png", "image/png", PNG)]
    answered = await _answer_with_screens(Model(), "sys", "task", shots, "lean task")
    looking = [user for user, with_images in seen if with_images]
    assert len(looking) == 2 and looking[0] == looking[1]
    assert "All screenshots of this review (22)" in looking[0] and "cook-mode-open.png" in looking[0]
    assert [note["screenshot"] for note in answered.answer[NOTES_KEY]] == ["s00.png", "s20.png"]


@pytest.mark.asyncio
@pytest.mark.parametrize("check, ships", [("LF2", False), ("layout", True)])
async def test_a_missed_look_blocks_the_automatic_accept_and_the_notes_stay_on_the_record(db, tmp_path, check,
                                                                                        ships):
    from app.services.workflow_runs.review.reading import NOTES_KEY, SCREENS_RULE
    from app.services.workflow_runs.review.runner import run_due_reviews
    from tests.review_convergence_support import _delivery, _started
    from tests.test_workflow_run_pause import _turn

    run, session = await _started(db, tmp_path, _delivery(tmp_path, {"tasks": False, "auto_revise": 0},
                                                           {"screens": True}))
    root = Path(session.metadata_["workspace_root"])
    (root / "test-reports" / "screenshots").mkdir(parents=True)
    (root / "test-reports" / "screenshots" / "search-results.png").write_bytes(PNG)
    await _turn(db, session.id, ["knowledge_search"])
    run.context = {**dict(run.context or {}), "local_path": str(root)}
    await db.commit()
    systems = []

    class Reviewer:
        async def factory(self, db, *, project_id, reviewer=None):
            return self

        async def answer(self, *, system, user, images=None):
            systems.append(system)
            if images:
                return ReviewAnswer({"audit": [{"screenshot": "search-results.png", "check": check,
                                                "severity": "high", "problem": "flat blocks, no gradient"}]},
                                    ReviewUsage(model="m", tokens_in=1, tokens_out=1))
            return ReviewAnswer({"verdict": "pass", "summary": "ok", "findings": []},
                                ReviewUsage(model="m", tokens_in=1, tokens_out=1))

    assert await run_due_reviews(db, model_factory=Reviewer().factory) == 1
    await db.refresh(run)
    assert SCREENS_RULE in systems[0] and "Look and feel list" in SCREENS_RULE
    review = run.context["review"]
    assert review[NOTES_KEY][0]["check"] == check
    assert (run.status == "completed") is ships
    if not ships:
        assert review["verdict"] == "changes" and review["findings"][0]["severity"] == "high"
        assert review["findings"][0]["file"] == "search-results.png"
        assert run.node_state["waiting"]["subject"] == "decisions"
