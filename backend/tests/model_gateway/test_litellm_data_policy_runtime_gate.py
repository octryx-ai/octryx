"""The gateway runtime admits a permitted classification and denies excessive, missing, unknown or unestablishable ones before a client exists."""

from __future__ import annotations

from app.agent.core.runtime.runtime_admission_contract import (
    RUNTIME_ADMISSION_DENIAL_KEY,
    RUNTIME_ADMISSION_DENIED_STATUS,
    build_admission_denied_attempt,
)
from app.agent.core.runtime.runtime_errors import (
    NON_FALLBACKABLE_RUNTIME_ERROR_CLASSES,
    RUNTIME_ERROR_ALIAS_DENIED,
    RUNTIME_ERROR_DATA_POLICY_DENIED,
)
from app.models import Project
from app.services.model_gateway.data_policy import (
    CLASSIFICATION_SOURCE_UNRESOLVED,
    DENIAL_CLASS_INSUFFICIENT,
    DENIAL_WORKSPACE_CLASS_MISSING,
    DENIAL_WORKSPACE_CLASS_UNKNOWN,
    resolve_data_classification,
)
from app.services.model_gateway.litellm import admit_gateway_runtimes, apply_model_policy_to_runtimes
from app.services.model_gateway.litellm.errors import GATEWAY_STATE_ALIAS_DENIED, GATEWAY_STATE_DATA_POLICY_DENIED
from tests.model_gateway.conftest import (
    PROJECT_ID,
    backup_runtime,
    gateway_runtime,
    granted_project_config,
    workspace_classification,
)
from tests.model_gateway.litellm_data_policy_support import _alias_section

# ---------------------------------------------------------------------------
# The runtime boundary: zero dispatch, closed evidence
# ---------------------------------------------------------------------------


def test_a_permitted_classification_admits_the_gateway_runtime() -> None:
    admitted = apply_model_policy_to_runtimes(
        [gateway_runtime(), backup_runtime()],
        project_config=granted_project_config(),
        project_id=PROJECT_ID,
        data_classification=workspace_classification("public"),
    )

    assert all(RUNTIME_ADMISSION_DENIAL_KEY not in runtime for runtime in admitted)


def test_an_excessive_classification_annotates_instead_of_dispatching() -> None:
    admitted = apply_model_policy_to_runtimes(
        [gateway_runtime(), backup_runtime()],
        project_config=granted_project_config(),
        project_id=PROJECT_ID,
        data_classification=workspace_classification("restricted"),
    )

    denial = admitted[0][RUNTIME_ADMISSION_DENIAL_KEY]
    assert denial["error_class"] == RUNTIME_ERROR_DATA_POLICY_DENIED
    assert denial["reason"] == DENIAL_CLASS_INSUFFICIENT
    assert denial["evidence"]["gateway_state"] == GATEWAY_STATE_DATA_POLICY_DENIED
    assert denial["evidence"]["workspace_data_classification"] == "restricted"
    assert denial["evidence"]["data_policy_class"] == "internal"
    # The message names neither the project nor the classification.
    assert PROJECT_ID not in denial["message"] and "restricted" not in denial["message"]
    # The non-gateway target is untouched: only gateway targets are governed here.
    assert RUNTIME_ADMISSION_DENIAL_KEY not in admitted[1]


def test_a_missing_or_unknown_classification_denies_at_the_runtime_boundary() -> None:
    cases = {
        DENIAL_WORKSPACE_CLASS_MISSING: resolve_data_classification(project_data_policy={}),
        DENIAL_WORKSPACE_CLASS_UNKNOWN: resolve_data_classification(
            project_data_policy={"classification": "unclassifiable"}
        ),
    }

    observed = {}
    for expected, classification in cases.items():
        admitted = apply_model_policy_to_runtimes(
            [gateway_runtime()],
            project_config=granted_project_config(),
            project_id=PROJECT_ID,
            data_classification=classification,
        )
        denial = admitted[0][RUNTIME_ADMISSION_DENIAL_KEY]
        observed[expected] = denial["reason"]
        assert denial["error_class"] == RUNTIME_ERROR_DATA_POLICY_DENIED
        # An unusable classification carries no classification value.
        assert denial["evidence"]["workspace_data_classification_source"] == CLASSIFICATION_SOURCE_UNRESOLVED
        assert "workspace_data_classification" not in denial["evidence"]

    assert observed == {reason: reason for reason in cases}


def test_an_omitted_classification_denies_rather_than_defaulting() -> None:
    """The kwarg default is the unresolved value, so forgetting it fails closed."""

    admitted = apply_model_policy_to_runtimes(
        [gateway_runtime()],
        project_config=granted_project_config(),
        project_id=PROJECT_ID,
    )

    assert admitted[0][RUNTIME_ADMISSION_DENIAL_KEY]["reason"] == DENIAL_WORKSPACE_CLASS_MISSING


def test_an_unestablishable_alias_class_denies_before_a_client_exists() -> None:
    """A catalog the runtime boundary cannot read is not a permissive allowance."""

    runtimes = (
        gateway_runtime(config_json=_alias_section("not-a-class")),
        gateway_runtime(config_json={}),
    )

    for runtime in runtimes:
        admitted = apply_model_policy_to_runtimes(
            [runtime],
            project_config=granted_project_config(),
            project_id=PROJECT_ID,
            data_classification=workspace_classification(),
        )
        denial = admitted[0][RUNTIME_ADMISSION_DENIAL_KEY]
        # The catalog owns the reason; the boundary does not invent one.
        assert denial["error_class"] == RUNTIME_ERROR_ALIAS_DENIED
        assert denial["evidence"]["gateway_state"] == GATEWAY_STATE_ALIAS_DENIED
        assert denial["reason"] in {"alias_data_policy_class_invalid", "alias_catalog_missing"}


def test_the_denial_is_a_zero_dispatch_attempt_the_chain_survives() -> None:
    assert RUNTIME_ERROR_DATA_POLICY_DENIED not in NON_FALLBACKABLE_RUNTIME_ERROR_CLASSES
    admitted = apply_model_policy_to_runtimes(
        [gateway_runtime(), backup_runtime()],
        project_config=granted_project_config(),
        project_id=PROJECT_ID,
        data_classification=workspace_classification("confidential"),
    )

    attempt = build_admission_denied_attempt(
        admitted[0],
        admitted[0][RUNTIME_ADMISSION_DENIAL_KEY],
        retry_cycle_index=0,
    )

    assert attempt["dispatched"] is False
    assert attempt["status"] == RUNTIME_ADMISSION_DENIED_STATUS
    assert attempt["error_class"] == RUNTIME_ERROR_DATA_POLICY_DENIED
    assert attempt["error_class_source"] == "explicit"
    assert attempt["admission_reason"] == DENIAL_CLASS_INSUFFICIENT
    assert attempt["admission_evidence"]["workspace_data_classification"] == "confidential"


async def test_the_run_preparation_seam_resolves_and_admits(db) -> None:
    """The one seam run preparation calls: project row -> classification -> chain."""

    project = Project(
        id="project-seam",
        name="seam-project",
        config={"data_policy": {"classification": "confidential"}},
    )
    db.add(project)
    await db.commit()

    denied = await admit_gateway_runtimes(
        db,
        [gateway_runtime()],
        project_config=granted_project_config(),
        project_id=project.id,
        session_metadata={},
    )
    admitted = await admit_gateway_runtimes(
        db,
        [gateway_runtime(config_json=_alias_section("confidential"))],
        project_config=granted_project_config(),
        project_id=project.id,
        session_metadata={},
    )

    assert denied[0][RUNTIME_ADMISSION_DENIAL_KEY]["reason"] == DENIAL_CLASS_INSUFFICIENT
    assert RUNTIME_ADMISSION_DENIAL_KEY not in admitted[0]
