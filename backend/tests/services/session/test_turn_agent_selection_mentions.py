"""Selection sources are a closed contract, only an exact configured-name mention selects an agent, only a workflow definition excludes a delivery agent, and prompt wording never selects one."""

import uuid
from types import SimpleNamespace

import pytest

from app.models import Project
from app.services.execution_strategy_intent import ROUTING_INTENT_SOURCE_POLICY
from app.services.session.agent_selection_sources import AGENT_SELECTION_SOURCES
from app.services.session.turn_agent_mention import NamedAgent, mentioned_agent_id
from app.services.session.turn_agent_selection import workflow_excludes_agent_type
from app.services.session.turn_refusals import TurnRefusalState, TurnRefusedError
from app.services.workspace_composition import seed_workspace_bundle_foundation
from tests.support.turn_agent_selection_support import _admin, _agent
from tests.turn_preparation_support import prepare_chat_turn

_AGENTS = [
    NamedAgent(agent_id="backend", name="Backend"),
    NamedAgent(agent_id="backend-engineer", name="Backend Engineer Agent"),
    NamedAgent(agent_id="reviewer", name="Reviewer"),
]


def _routing(*, intent: str, source: str) -> SimpleNamespace:
    return SimpleNamespace(routing_intent=intent, strategy_decision=SimpleNamespace(routing_intent_source=source))


# Prompts that name an agent's domain: wording never selects an agent of this Workspace.
_DOMAIN_WORDED_PROMPTS = [
    "Create a new Jira release and assign 3 tickets to the owner.",
    "Plan a Jira sprint, create a release, assign tickets, and set priorities for the next delivery.",
    "Investigate the Kubernetes incident. Several pods are crashing in production.",
    "Implement the service integration and refactor the backend API flow for the next release.",
    "Erstelle mir eine Präsentation mit 10 Slides über Vorteile und Risiken von LLM Agents im Unternehmen.",
]


async def _domain_agents_workspace(db, *, default_agent: bool) -> SimpleNamespace:
    admin = await _admin(db)
    project = Project(id=str(uuid.uuid4()), name=f"mention-only-{uuid.uuid4()}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    jira = _agent(admin.id, project.id, "Jira Release Coordinator")
    jira.description = "Handle Jira release preparation and ticket assignment."
    k8s = _agent(admin.id, project.id, "Kubernetes Incident Responder", agent_type="diagnosis")
    k8s.description = "Investigate Kubernetes incidents, pods, rollouts and cluster failures."
    backend = _agent(admin.id, project.id, "Backend Engineer Agent")
    backend.description = "Analyze backend code, APIs, integrations and delivery paths."
    deck = _agent(admin.id, project.id, "Presentation Designer")
    deck.description = "Design structured PowerPoint decks, presentation storylines, and slides."
    fallback = _agent(admin.id, project.id, "Workspace Default Agent", agent_type="diagnosis")
    if default_agent:
        project.config = {"project_agent_preferences": {fallback.id: {"status": "primary"}}}
    db.add_all([jira, k8s, backend, deck, fallback])
    await db.commit()
    await seed_workspace_bundle_foundation(db, workspace_id=project.id)
    project.config = {}
    db.add(project)
    await db.commit()
    return SimpleNamespace(admin=admin, project=project, default_agent=fallback)


def test_selection_sources_are_the_closed_contract():
    assert AGENT_SELECTION_SOURCES == {"workflow_phase", "explicit", "session", "mention", "default",
                                       "platform_default", "none"}


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("@Backend Engineer Agent fix the API", "backend-engineer"),
        ("please ask @backend engineer agent, then report", "backend-engineer"),
        ("@Backend: check the logs", "backend"),
        ("(@Reviewer) take a look", "reviewer"),
        ("@Reviewer and again @Reviewer", "reviewer"),
    ],
)
def test_an_exact_configured_name_mention_selects_that_agent(prompt, expected):
    assert mentioned_agent_id(prompt, _AGENTS) == expected


@pytest.mark.parametrize(
    "prompt",
    [
        "@Backendish is not an agent",
        "@Backend-Engineer is not the configured name",
        "@Reviewers should look",
        "@Review the change",
        "mail ops@Reviewer.example about it",
        "Backend Engineer Agent without an at sign",
        "@ Reviewer with a space",
    ],
)
def test_a_near_miss_mention_selects_no_agent(prompt):
    assert mentioned_agent_id(prompt, _AGENTS) == ""


def test_mentions_of_different_agents_are_ambiguous_not_resolved():
    with pytest.raises(TurnRefusedError) as refused:
        mentioned_agent_id("@Reviewer check what @Backend did", _AGENTS)
    assert refused.value.refusal.state == TurnRefusalState.AGENT_MENTION_AMBIGUOUS

    duplicates = [NamedAgent(agent_id="a", name="Twin"), NamedAgent(agent_id="b", name="twin")]
    with pytest.raises(TurnRefusedError):
        mentioned_agent_id("@Twin go", duplicates)


def test_only_a_workflow_definition_can_exclude_a_delivery_agent():
    operations_workflow = _routing(intent="operations", source=ROUTING_INTENT_SOURCE_POLICY)
    assert workflow_excludes_agent_type(operations_workflow, "change")
    assert not workflow_excludes_agent_type(operations_workflow, "diagnosis")
    # The diagnosis default of a turn without a workflow never excludes an agent.
    assert not workflow_excludes_agent_type(_routing(intent="diagnosis", source="default"), "change")
    documentation_workflow = _routing(intent="documentation", source=ROUTING_INTENT_SOURCE_POLICY)
    assert not workflow_excludes_agent_type(documentation_workflow, "change")


@pytest.mark.asyncio
@pytest.mark.parametrize("default_agent", [False, True])
@pytest.mark.parametrize("prompt", _DOMAIN_WORDED_PROMPTS)
async def test_prompt_wording_never_selects_an_agent(db, prompt, default_agent):
    ws = await _domain_agents_workspace(db, default_agent=default_agent)
    session, _runtime, _thinking, payload = await prepare_chat_turn(
        db=db, user=ws.admin, prompt=prompt, project_id=ws.project.id, agent_type="change"
    )

    if default_agent:
        assert payload is not None and payload["id"] == ws.default_agent.id
        assert session.metadata_["agent_selection_source"] == "default"
    else:
        assert payload["builtinKey"] == "assistant"
        assert session.metadata_["agent_selection_source"] == "platform_default"
