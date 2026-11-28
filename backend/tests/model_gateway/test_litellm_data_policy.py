"""Data policy: the alias ``data_policy_class`` is a control, not a label."""

from __future__ import annotations

from app.models import Project
from app.services.model_gateway.data_policy import (
    CLASSIFICATION_SOURCE_PROJECT_CONFIG,
    CLASSIFICATION_SOURCE_SESSION_RAISE,
    CLASSIFICATION_SOURCE_UNRESOLVED,
    DATA_CLASSIFICATION_ORDER,
    DENIAL_ALIAS_CLASS_UNKNOWN,
    DENIAL_CLASS_INSUFFICIENT,
    DENIAL_CONTEXT_UNVERIFIABLE,
    DENIAL_SESSION_CLASS_UNKNOWN,
    DENIAL_WORKSPACE_CLASS_MISSING,
    DENIAL_WORKSPACE_CLASS_UNKNOWN,
    WorkspaceDataClassification,
    data_policy_decision,
    resolve_data_classification,
    resolve_workspace_data_classification,
)
from app.services.model_gateway.litellm.alias_catalog import DATA_POLICY_CLASSES
from app.services.model_gateway.litellm.errors import normalize_denial_reason
from tests.model_gateway.conftest import workspace_classification
from tests.model_gateway.litellm_data_policy_support import EXCESSIVE_CLASSIFICATIONS

# The alias in the shared fixtures is approved for ``internal`` data.
PERMITTED_CLASSIFICATIONS = ("public", "internal")


def test_the_compatibility_order_is_closed_and_ascending() -> None:
    assert DATA_CLASSIFICATION_ORDER == (
        "public",
        "internal",
        "confidential",
        "restricted",
        "secret",
    )
    # The alias vocabulary is the same order minus ``secret``, so a ``secret``
    # workspace has no admissible gateway alias by construction.
    assert DATA_POLICY_CLASSES == frozenset(DATA_CLASSIFICATION_ORDER[:-1])


def test_a_workspace_at_or_below_the_alias_allowance_is_permitted() -> None:
    for classification in PERMITTED_CLASSIFICATIONS:
        decision = data_policy_decision(workspace_classification(classification), "internal")
        assert decision.allowed is True
        assert decision.workspace_classification == classification
        assert decision.alias_data_policy_class == "internal"


def test_a_workspace_above_the_alias_allowance_is_refused() -> None:
    observed = {
        classification: data_policy_decision(workspace_classification(classification), "internal").reason
        for classification in EXCESSIVE_CLASSIFICATIONS
    }

    assert observed == dict.fromkeys(EXCESSIVE_CLASSIFICATIONS, DENIAL_CLASS_INSUFFICIENT)


def test_every_unusable_input_has_its_own_fixed_code() -> None:
    cases = {
        DENIAL_WORKSPACE_CLASS_MISSING: data_policy_decision(
            resolve_data_classification(project_data_policy={}), "internal"
        ),
        DENIAL_WORKSPACE_CLASS_UNKNOWN: data_policy_decision(
            resolve_data_classification(project_data_policy={"classification": "top-secret-ish"}),
            "internal",
        ),
        DENIAL_SESSION_CLASS_UNKNOWN: data_policy_decision(
            resolve_data_classification(
                project_data_policy={"classification": "internal"},
                session_data_policy={"classification": "extremely-secret"},
            ),
            "internal",
        ),
        DENIAL_ALIAS_CLASS_UNKNOWN: data_policy_decision(workspace_classification(), "confidentialish"),
        DENIAL_CONTEXT_UNVERIFIABLE: data_policy_decision(None, "internal"),
    }

    assert {reason: decision.reason for reason, decision in cases.items()} == {reason: reason for reason in cases}
    assert all(decision.allowed is False for decision in cases.values())
    # Every code survives the gateway error charset guard, so each one can be
    # carried in a fixed error message without becoming free text.
    assert all(normalize_denial_reason(reason) == reason for reason in cases)


def test_unknown_classification_values_never_enter_evidence() -> None:
    unknown_alias = data_policy_decision(workspace_classification(), "secret-from-input")
    forged_workspace = data_policy_decision(
        WorkspaceDataClassification("secret-from-input", CLASSIFICATION_SOURCE_PROJECT_CONFIG, ""),
        "internal",
    )

    assert unknown_alias.reason == DENIAL_ALIAS_CLASS_UNKNOWN
    assert "data_policy_class" not in unknown_alias.evidence()
    assert forged_workspace.reason == DENIAL_WORKSPACE_CLASS_UNKNOWN
    assert "workspace_data_classification" not in forged_workspace.evidence()


def test_a_session_may_only_raise_the_project_floor() -> None:
    raised = resolve_data_classification(
        project_data_policy={"classification": "internal"},
        session_data_policy={"classification": "restricted"},
    )
    lowered = resolve_data_classification(
        project_data_policy={"classification": "restricted"},
        session_data_policy={"classification": "public"},
    )
    equal = resolve_data_classification(
        project_data_policy={"classification": "internal"},
        session_data_policy={"classification": "internal"},
    )

    assert (raised.classification, raised.source) == ("restricted", CLASSIFICATION_SOURCE_SESSION_RAISE)
    # A session write can never weaken the project's authority.
    assert (lowered.classification, lowered.source) == ("restricted", CLASSIFICATION_SOURCE_PROJECT_CONFIG)
    assert (equal.classification, equal.source) == ("internal", CLASSIFICATION_SOURCE_PROJECT_CONFIG)


async def test_the_classification_is_read_from_the_project_row(db) -> None:
    project = Project(
        id="project-data-policy", name="data-policy-project", config={"data_policy": {"classification": "confidential"}}
    )
    db.add(project)
    await db.commit()

    resolved = await resolve_workspace_data_classification(db, project_id=project.id)

    assert resolved.classification == "confidential"
    assert resolved.source == CLASSIFICATION_SOURCE_PROJECT_CONFIG


async def test_a_missing_project_or_classification_resolves_unusable(db) -> None:
    unclassified = Project(id="project-unclassified", name="unclassified-project", config={})
    db.add(unclassified)
    await db.commit()

    for project_id in (None, "", "project-that-does-not-exist", unclassified.id):
        resolved = await resolve_workspace_data_classification(db, project_id=project_id)
        assert resolved.resolved is False
        assert resolved.source == CLASSIFICATION_SOURCE_UNRESOLVED
        assert resolved.reason == DENIAL_WORKSPACE_CLASS_MISSING


async def test_the_source_ignores_a_classification_the_merged_turn_config_carries(db) -> None:
    project = Project(
        id="project-override-attempt",
        name="override-attempt-project",
        config={"data_policy": {"classification": "restricted"}},
    )
    db.add(project)
    await db.commit()

    resolved = await resolve_workspace_data_classification(
        db,
        project_id=project.id,
        session_metadata={"data_policy": {"classification": "public"}},
    )

    assert resolved.classification == "restricted"
    assert resolved.source == CLASSIFICATION_SOURCE_PROJECT_CONFIG
