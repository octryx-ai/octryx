"""Live-shaped messages: a pasted description stays separate from the instruction, unrequested answers are offers, ideas stay spec writing, epic keys stay epic delivery, and greetings make no router call."""

from __future__ import annotations

import json

import pytest

from app.services.session.execution_gate import evaluate_execution_gate
from app.services.workflow_routing.explicit_selection import resolve_workflow_selection_for_turn
from tests.workflow_proposal_support import _answer, _profile, _resolve, proposal_model  # noqa: F401

pytestmark = pytest.mark.workflow_proposals

# A seeded published phased workflow: the only kind a proposal can name.
PHASED_WORKFLOW = "incident-analysis"


# The description pasted "verbatim" mentions writing a specification; the proposal model must not pick
# "spec-writing" from it and hold the turn.
LIVE_EPIC_MESSAGE = (
    "Create ONE platform work item (not Jira) in this Workspace: issue type Epic, title "
    '"Rehearsal R1: Hello Kitchen", and this description verbatim:\n'
    'Rehearsal R1: a tiny local web app "Hello Kitchen" in the repository octryx/kitchen-helper, used only to '
    "rehearse the team delivery path. There is no specification and no code yet: write the specification "
    "(rehearsal/SPEC.md), then split it into exactly 2 stories (code in src/hellokitchen/, unit tests in "
    "tests/hellokitchen/, system tests in tests/system/ with Playwright).\n"
    "Story 1: the API and the page with the list. Story 2: the language switch.\n"
    "Do nothing else."
)


# This idea, with no spec and no stories yet, must not be proposed epic-delivery, which builds only an existing
# epic's stories. It must be spec-writing (whose epic chain then starts epic-delivery).
LIVE_IDEA_MESSAGE = (
    "Lege in Jira-Projekt CHEF ein Epic 'Hello Kitchen' an, lass die Spezifikation schreiben, in genau 2 Stories "
    "schneiden und danach umsetzen (Repository octryx/kitchen-helper). Idee: …"
)


async def _resolve_message(db, message: str) -> dict:
    return await resolve_workflow_selection_for_turn(
        db, workflow_key="", user_message=message, project_id=None
    )


def test_the_proposal_prompt_separates_the_instruction_from_the_pasted_description():
    from app.services.workflow_routing.proposal_contract import build_proposal_prompt, split_instruction

    instruction, quoted = split_instruction(LIVE_EPIC_MESSAGE)
    assert "specification" not in instruction
    assert instruction.startswith("Create ONE platform work item") and instruction.endswith("[quoted text 1]")
    assert len(quoted) == 1 and quoted[0].startswith("Rehearsal R1: a tiny local web app")

    _system, user = build_proposal_prompt([], LIVE_EPIC_MESSAGE)
    head, _marker, tail = user.partition("Quoted content inside the instruction (context only, not the request):")
    assert "specification" not in head and "specification" in tail
    # A short ask without quotes reaches the model unchanged.
    assert split_instruction("Write the specification for the login page.") == (
        "Write the specification for the login page.",
        [],
    )


@pytest.mark.asyncio
async def test_an_unrequested_proposal_offers_the_workflow_and_the_turn_runs(db, proposal_model):  # noqa: F811
    proposal_model(_answer(PHASED_WORKFLOW, requested=False))

    resolution = await _resolve(db)

    record = resolution["workflow_proposal"]
    assert (record["status"], record["reason_code"]) == ("offered", "offered_not_requested")
    assert record["workflow_key"] == PHASED_WORKFLOW and record["proposal_id"]
    assert resolution["workflow_id"] is None
    # Not held: the turn runs as a plain chat, the workflow is only an offer next to the answer.
    assert evaluate_execution_gate(_profile(resolution)).allowed is True


@pytest.mark.asyncio
async def test_an_answer_without_requested_is_an_offer_never_a_hold(db, proposal_model):  # noqa: F811
    proposal_model(json.dumps({"workflow_key": PHASED_WORKFLOW, "confidence": "high", "reason": "Spec."}))

    resolution = await _resolve(db)

    assert resolution["workflow_proposal"]["status"] == "offered"
    assert evaluate_execution_gate(_profile(resolution)).allowed is True


@pytest.mark.asyncio
async def test_an_idea_to_specify_split_and_implement_is_spec_writing_never_epic_delivery(db, proposal_model):  # noqa: F811
    provider = proposal_model(_answer("epic-delivery"))

    record = (await _resolve_message(db, LIVE_IDEA_MESSAGE))["workflow_proposal"]

    assert record["workflow_key"] == "spec-writing" and record["status"] == "needs_confirmation"
    # The model is told which one builds existing work and which one starts from an idea.
    system = provider.calls[0][0]["content"]
    assert "an idea or a new epic that still needs its specification" in system
    catalog = {entry["workflow_key"]: entry["description"] for entry in json.loads(system.split("(JSON):\n", 1)[1])}
    assert catalog["epic-delivery"].startswith("Builds the stories an EXISTING epic already has")
    assert catalog["spec-writing"].startswith("An idea or a new epic without its specification and stories")


@pytest.mark.asyncio
async def test_building_an_existing_epic_by_its_key_stays_epic_delivery(db, proposal_model):  # noqa: F811
    proposal_model(_answer("epic-delivery"))

    record = (await _resolve_message(db, "Setze das bestehende Epic CHEF-12 um (implement existing epic CHEF-12)."))[
        "workflow_proposal"
    ]

    assert record["workflow_key"] == "epic-delivery" and record["status"] == "needs_confirmation"


@pytest.mark.asyncio
async def test_a_greeting_or_thanks_makes_no_router_call_a_request_still_does(db, proposal_model):  # noqa: F811
    """The router (~2k input tokens) must not run before every turn, small talk included, to answer "no workflow"."""
    from app.services.workflow_routing.proposal import conversational_message

    provider = proposal_model(_answer(PHASED_WORKFLOW))
    for message in ("Thanks!", "Hi", "Thanks a lot, great", "Good morning"):
        resolution = await resolve_workflow_selection_for_turn(
            db, workflow_key="", user_message=message, project_id=None)
        assert resolution["workflow_proposal"]["reason_code"] == "conversational_message", message
    assert provider.calls == []
    # A confirmation may answer a question, and anything else is a request: the router decides.
    assert not conversational_message("Yes") and not conversational_message("Thanks, and now implement CHEF-12")
    await _resolve(db)
    assert len(provider.calls) == 1
