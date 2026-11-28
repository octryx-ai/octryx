"""Server-owned Workspace admission at every dispatch boundary."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project
from app.services.model_gateway.dispatch_admission import (
    DISPATCH_STATE_ALLOWED,
    DISPATCH_STATE_DENIED,
    DISPATCH_STATE_NEEDS_CONFIGURATION,
    REASON_CONTEXT_MISSING,
    REASON_CONTEXT_NOT_AUTHORIZED,
    REASON_CONTEXT_UNRESOLVABLE,
    DispatchAdmissionDeniedError,
    admit_client_kwargs_for_dispatch,
    admit_runtimes_for_dispatch,
    resolve_workspace_admission,
)
from app.services.model_gateway.dispatch_owner_record import DISPATCH_MODE_ADMITTED
from app.services.model_gateway.dispatch_owners import owners_for_mode
from app.services.model_gateway.litellm.policy import (
    POLICY_REASON_EXPLICIT_DENY,
    POLICY_REASON_NOT_GRANTED,
)
from app.services.model_gateway.litellm.runtime_admission import ADMISSION_DENIAL_KEY
from tests.factories import make_project

from .conftest import ALIAS, backup_runtime, gateway_runtime

OWNER = "knowledge_graph_runtime"


async def _project(db: AsyncSession, *, policy: dict | None, is_active: bool = True) -> Project:
    return await make_project(
        db,
        name=f"admission-{uuid.uuid4().hex[:8]}",
        config={
            **({"model_policy": policy} if policy is not None else {}),
            "data_policy": {"classification": "internal"},
        },
        is_active=is_active,
    )


async def test_a_granting_workspace_carries_a_verified_admission(db: AsyncSession):
    project = await _project(db, policy={"allowed_aliases": [ALIAS]})

    admission = await admit_runtimes_for_dispatch(
        db, [gateway_runtime()], project_ids=project.id, owner=OWNER
    )

    assert admission.state == DISPATCH_STATE_ALLOWED
    runtime = admission.first_dispatchable_runtime()
    carried = runtime["project_model_admission"]
    assert carried.verified is True
    assert carried.project_id == project.id
    assert carried.source == OWNER


async def test_a_caller_cannot_supply_the_policy_only_the_project(db: AsyncSession):
    project = await _project(db, policy={"denied_aliases": [ALIAS]})

    admission = await admit_runtimes_for_dispatch(
        db,
        [
            gateway_runtime(
                model_policy={"allow_all_admitted_aliases": True},
                project_config={"model_policy": {"allowed_aliases": [ALIAS]}},
                project_id="some-other-project",
                project_model_admission="not-a-typed-admission",
            )
        ],
        project_ids=project.id,
        owner=OWNER,
    )

    assert admission.state == DISPATCH_STATE_DENIED
    assert admission.reason == POLICY_REASON_EXPLICIT_DENY
    assert admission.dispatchable_runtimes() == ()


async def test_no_workspace_is_needs_configuration_not_an_allow(db: AsyncSession):
    admission = await admit_runtimes_for_dispatch(db, [gateway_runtime()], project_ids=None, owner=OWNER)

    assert admission.state == DISPATCH_STATE_NEEDS_CONFIGURATION
    assert admission.reason == REASON_CONTEXT_MISSING
    assert admission.to_result()["dispatched"] is False


@pytest.mark.parametrize("scenario", ["unknown", "inactive"])
async def test_an_unresolvable_workspace_is_denied(db: AsyncSession, scenario: str):
    if scenario == "unknown":
        project_id = str(uuid.uuid4())
    else:
        project_id = (await _project(db, policy={"allowed_aliases": [ALIAS]}, is_active=False)).id

    admission = await admit_runtimes_for_dispatch(
        db, [gateway_runtime()], project_ids=project_id, owner=OWNER
    )

    assert admission.state == DISPATCH_STATE_DENIED
    assert admission.reason == REASON_CONTEXT_UNRESOLVABLE


async def test_a_workspace_outside_the_authorized_scope_is_refused(db: AsyncSession):
    project = await _project(db, policy={"allow_all_admitted_aliases": True})

    admission = await admit_runtimes_for_dispatch(
        db,
        [gateway_runtime()],
        project_ids=project.id,
        owner="call_agent",
        authorized_project_ids=[str(uuid.uuid4())],
    )

    assert admission.state == DISPATCH_STATE_DENIED
    assert admission.reason == REASON_CONTEXT_NOT_AUTHORIZED


async def test_a_multi_workspace_scope_is_admitted_by_intersection(db: AsyncSession):
    granting = await _project(db, policy={"allowed_aliases": [ALIAS]})
    other_granting = await _project(db, policy={"allow_all_admitted_aliases": True})
    silent = await _project(db, policy={})

    admitted = await admit_runtimes_for_dispatch(
        db, [gateway_runtime()], project_ids=[granting.id, other_granting.id], owner=OWNER
    )
    assert admitted.state == DISPATCH_STATE_ALLOWED
    # The anchor is the first project in the caller's scope.
    assert admitted.first_dispatchable_runtime()["project_model_admission"].project_id == granting.id

    partial = await admit_runtimes_for_dispatch(
        db, [gateway_runtime()], project_ids=[granting.id, silent.id], owner=OWNER
    )
    assert partial.state == DISPATCH_STATE_DENIED
    assert partial.reason == POLICY_REASON_NOT_GRANTED


async def test_a_denied_gateway_target_is_annotated_never_dropped(db: AsyncSession):
    project = await _project(db, policy={})

    admission = await admit_runtimes_for_dispatch(
        db, [gateway_runtime(), backup_runtime()], project_ids=project.id, owner=OWNER
    )

    # A non-gateway fallback keeps the chain alive, and the refusal stays visible.
    assert admission.state == DISPATCH_STATE_ALLOWED
    assert len(admission.runtimes) == 2
    denial = admission.runtimes[0][ADMISSION_DENIAL_KEY]
    assert denial["reason"] == POLICY_REASON_NOT_GRANTED
    assert admission.runtimes[1].get(ADMISSION_DENIAL_KEY) is None
    assert admission.first_dispatchable_runtime()["provider_name"] == "backup"


async def test_a_chain_without_a_gateway_target_is_untouched_and_reads_nothing(db: AsyncSession):
    admission = await admit_runtimes_for_dispatch(db, [backup_runtime()], project_ids=None, owner=OWNER)

    assert admission.state == DISPATCH_STATE_ALLOWED
    assert admission.runtimes == (backup_runtime(),)
    assert "project_model_admission" not in admission.runtimes[0]


async def test_denial_evidence_is_bounded_and_carries_no_policy_contents(db: AsyncSession):
    project = await _project(
        db,
        policy={"denied_aliases": [ALIAS], "allowed_aliases": ["secret-internal-alias"]},
    )

    admission = await admit_runtimes_for_dispatch(
        db, [gateway_runtime()], project_ids=project.id, owner=OWNER
    )
    result = admission.to_result()

    assert set(result) == {"status", "dispatch_owner", "admission_reason", "admission_evidence", "dispatched"}
    evidence = result["admission_evidence"]
    assert evidence == {
        "gateway": "litellm_gateway",
        "gateway_state": "alias_denied",
        "denial_reason": POLICY_REASON_EXPLICIT_DENY,
        "alias": ALIAS,
        "project_admission_source": OWNER,
        "dispatch_owner": OWNER,
        "project_scope_size": 1,
    }
    serialized = repr(result)
    assert project.id not in serialized
    assert "secret-internal-alias" not in serialized


async def test_client_kwargs_owners_reach_the_same_decision(db: AsyncSession):
    project = await _project(db, policy={"allowed_aliases": [ALIAS]})

    granted = await admit_client_kwargs_for_dispatch(
        db,
        {"provider_name": "litellm", "driver": "litellm_gateway"},
        model=ALIAS,
        project_ids=project.id,
        owner="security_analyzer_llm_risk",
    )
    assert granted.state == DISPATCH_STATE_ALLOWED
    # The alias decides admission; it is not a constructor field, so the admitted
    # runtime is the caller's own kwargs plus the carried admission — an owner that
    # splats this into ``get_provider`` passes exactly what it passed before.
    admitted = granted.first_dispatchable_runtime()
    assert set(admitted) == {"provider_name", "driver", "project_model_admission"}
    assert admitted["project_model_admission"].verified is True

    denied = await admit_client_kwargs_for_dispatch(
        db,
        {"provider_name": "litellm", "driver": "litellm_gateway"},
        model="some-other-alias",
        project_ids=project.id,
        owner="security_analyzer_llm_risk",
    )
    assert denied.state == DISPATCH_STATE_DENIED
    assert DispatchAdmissionDeniedError(denied).to_result()["dispatched"] is False


async def test_an_unregistered_owner_cannot_obtain_an_admission(db: AsyncSession):
    with pytest.raises(ValueError):
        await resolve_workspace_admission(db, project_ids="anything", owner="some_new_consumer")


async def test_the_authority_owner_cannot_resolve_a_workspace(db: AsyncSession):
    with pytest.raises(ValueError):
        await resolve_workspace_admission(db, project_ids="anything", owner="engine_runtime_chain")


async def test_every_admitted_category_denies_without_a_workspace_and_admits_with_one(db: AsyncSession):
    project = await _project(db, policy={"allowed_aliases": [ALIAS]})
    for owner in owners_for_mode(DISPATCH_MODE_ADMITTED):
        denied = await admit_runtimes_for_dispatch(
            db, [gateway_runtime()], project_ids=None, owner=owner.key
        )
        assert denied.state == DISPATCH_STATE_NEEDS_CONFIGURATION, owner.key
        assert denied.dispatchable_runtimes() == (), owner.key

        allowed = await admit_runtimes_for_dispatch(
            db, [gateway_runtime()], project_ids=project.id, owner=owner.key
        )
        assert allowed.state == DISPATCH_STATE_ALLOWED, owner.key
        carried = allowed.first_dispatchable_runtime()["project_model_admission"]
        assert carried.verified is True, owner.key
        assert carried.source == owner.key, owner.key
