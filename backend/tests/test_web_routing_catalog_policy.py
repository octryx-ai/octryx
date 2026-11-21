from app.models import AgentDefinition, AgentStep
from app.services.agent_catalog_policy import (
    AGENT_CATALOG_CATEGORY_DEFINITIONS as _AGENT_CATALOG_CATEGORY_DEFINITIONS,
)
from app.services.agent_catalog_policy import (
    agent_catalog_group_payload as _agent_catalog_group_payload,
)
from app.services.agent_catalog_policy import (
    agent_catalog_priority_score as _agent_catalog_priority_score,
)
from app.services.agent_catalog_policy import (
    classify_agent_catalog_entry as _classify_agent_catalog_entry,
)
from app.services.agent_catalog_policy import (
    serialize_chat_agent_option as _serialize_chat_agent_option,
)


def _build_agent(**overrides) -> AgentDefinition:
    payload = {
        "id": "agent-1",
        "owner_id": "user-1",
        "name": "Backend Engineer",
        "description": "",
        "goal": "",
        "agent_type": "chat",
    }
    payload.update(overrides)
    return AgentDefinition(**payload)


def test_catalog_policy_exports_classify_engineering_agents() -> None:
    category_id, category_name, is_core = _classify_agent_catalog_entry(
        agent=_build_agent(description="Coding implementation support"),
    )

    assert (category_id, category_name, is_core) == ("engineering", "Engineering", True)


def test_catalog_priority_score_preserves_existing_weighting() -> None:
    agent = _build_agent(name="Jira Sprint Planner")
    agent.steps = [
        AgentStep(id="step-1", agent_id="agent-1", name="Plan"),
        AgentStep(id="step-2", agent_id="agent-1", name="Prioritize"),
    ]

    score = _agent_catalog_priority_score(
        agent=agent,
        category_id="delivery-pm",
    )

    assert score == 42


def test_catalog_policy_exports_preserve_payload_contract() -> None:
    agent = _build_agent(name="Presentation Designer", description="Deck specialist")

    payload = _serialize_chat_agent_option(
        agent=agent,
        category_id="reporting",
        category_name="Reporting",
        is_core=True,
        is_primary=False,
    )

    assert _AGENT_CATALOG_CATEGORY_DEFINITIONS[-1] == ("specialized", "Specialized")
    assert _agent_catalog_group_payload("reporting", "Reporting", agent_count=3) == {
        "id": "reporting",
        "name": "Reporting",
        "slug": "reporting",
        "description": "Reporting agent catalog",
        "category": "catalog",
        "projectId": None,
        "position": 0,
        "isActive": True,
        "agentCount": 3,
    }
    assert payload == {
        "id": "agent-1",
        "name": "Presentation Designer",
        "description": "Deck specialist",
        "agentType": "chat",
        "groupId": "reporting",
        "groupName": "Reporting",
        "category": "Reporting",
        "isCore": True,
        "isPrimary": False,
    }
