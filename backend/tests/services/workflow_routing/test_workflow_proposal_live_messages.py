"""Live-shaped messages: a pasted description stays separate from the instruction, unrequested answers are offers, ideas stay spec writing, epic keys stay epic delivery, and greetings make no router call."""

from __future__ import annotations

import pytest

from tests.workflow_proposal_support import _answer, _profile, _resolve, proposal_model  # noqa: F401

pytestmark = pytest.mark.workflow_proposals

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




def test_the_proposal_prompt_separates_the_instruction_from_the_pasted_description():
    from app.services.workflow_routing.proposal_contract import build_proposal_prompt, split_instruction

    instruction, quoted = split_instruction(LIVE_EPIC_MESSAGE)
    assert "specification" not in instruction
    assert instruction.startswith("Create ONE platform work item") and instruction.endswith("[quoted text 1]")
    assert len(quoted) == 1 and quoted[0].startswith("Rehearsal R1: a tiny local web app")

    _system, user = build_proposal_prompt([], LIVE_EPIC_MESSAGE)
    head, _marker, tail = user.partition("Quoted content inside the instruction (context only, not the request):")
    assert "specification" not in head and "specification" in tail
    assert split_instruction("Write the specification for the login page.") == (
        "Write the specification for the login page.",
        [],
    )










