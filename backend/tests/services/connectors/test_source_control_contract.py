from __future__ import annotations

import pytest

from app.services.source_control import (
    SourceControlContractError,
    SourceControlMutation,
    SourceControlOperation,
    SourceControlOperationRequest,
    SourceControlOperationResult,
    SourceControlPolicyCheck,
    SourceControlProvider,
    SourceControlRepositoryMode,
    SourceControlRepositoryRef,
    get_source_control_operation_contract,
    list_source_control_operation_contracts,
)


def test_source_control_contract_covers_required_operations():
    contracts = {contract.operation: contract for contract in list_source_control_operation_contracts()}

    assert set(contracts) == set(SourceControlOperation)
    assert contracts[SourceControlOperation.PREPARE_REPOSITORY].repository_operation == "branch"
    assert contracts[SourceControlOperation.READ_FILE].repository_operation == "read"
    assert contracts[SourceControlOperation.LIST_BRANCHES].repository_operation == "read"
    assert contracts[SourceControlOperation.CREATE_BRANCH].repository_operation == "branch"
    assert contracts[SourceControlOperation.COMMIT].repository_operation == "write"
    assert contracts[SourceControlOperation.PUSH].repository_operation == "write"
    assert contracts[SourceControlOperation.CREATE_CHANGE_REQUEST].repository_operation == "pr"
    assert contracts[SourceControlOperation.GET_CHANGE_REQUEST].repository_operation == "read"
    assert contracts[SourceControlOperation.UPDATE_CHANGE_REQUEST].repository_operation == "pr"
    assert contracts[SourceControlOperation.LIST_CHANGE_REQUESTS].repository_operation == "read"
    assert contracts[SourceControlOperation.LIST_PIPELINES].repository_operation == "read"


def test_source_control_contract_marks_repository_modes_and_mutations():
    readonly = get_source_control_operation_contract(SourceControlOperation.READ_FILE)
    prepare = get_source_control_operation_contract(SourceControlOperation.PREPARE_REPOSITORY)
    push = get_source_control_operation_contract(SourceControlOperation.PUSH)
    create_request = get_source_control_operation_contract(SourceControlOperation.CREATE_CHANGE_REQUEST)

    assert readonly.repository_mode == SourceControlRepositoryMode.READONLY
    assert readonly.mutation == SourceControlMutation.NONE
    assert prepare.repository_mode == SourceControlRepositoryMode.BRANCH
    assert prepare.mutates_workspace is True
    assert prepare.mutates_remote is False
    assert push.repository_mode == SourceControlRepositoryMode.WRITE
    assert push.mutates_remote is True
    assert create_request.repository_mode == SourceControlRepositoryMode.DELIVERY
    assert create_request.mutates_remote is True


@pytest.mark.parametrize(
    "operation",
    [
        SourceControlOperation.READ_FILE,
        SourceControlOperation.LIST_BRANCHES,
        SourceControlOperation.CREATE_BRANCH,
        SourceControlOperation.PREPARE_REPOSITORY,
        SourceControlOperation.COMMIT,
        SourceControlOperation.PUSH,
        SourceControlOperation.CREATE_CHANGE_REQUEST,
        SourceControlOperation.GET_CHANGE_REQUEST,
        SourceControlOperation.UPDATE_CHANGE_REQUEST,
        SourceControlOperation.LIST_CHANGE_REQUESTS,
        SourceControlOperation.LIST_PIPELINES,
    ],
)
def test_repository_scoped_operations_require_repository_policy(operation):
    contract = get_source_control_operation_contract(operation)

    assert SourceControlPolicyCheck.CONNECTOR_ACTIVE in contract.required_policy_checks
    assert SourceControlPolicyCheck.TOOL_VISIBLE in contract.required_policy_checks
    assert SourceControlPolicyCheck.REPOSITORY_CONFIGURED in contract.required_policy_checks
    assert SourceControlPolicyCheck.REPOSITORY_OPERATION_POLICY in contract.required_policy_checks
    assert SourceControlPolicyCheck.EVIDENCE_REDACTION in contract.required_policy_checks


@pytest.mark.parametrize(
    "operation",
    [
        SourceControlOperation.CREATE_BRANCH,
        SourceControlOperation.COMMIT,
        SourceControlOperation.PUSH,
        SourceControlOperation.CREATE_CHANGE_REQUEST,
        SourceControlOperation.UPDATE_CHANGE_REQUEST,
    ],
)
def test_mutating_operations_require_approval_policy(operation):
    contract = get_source_control_operation_contract(operation)

    assert SourceControlPolicyCheck.APPROVAL_POLICY in contract.required_policy_checks


@pytest.mark.parametrize(
    "operation",
    [
        SourceControlOperation.PREPARE_REPOSITORY,
        SourceControlOperation.COMMIT,
        SourceControlOperation.PUSH,
    ],
)
def test_workspace_operations_require_workspace_boundary(operation):
    contract = get_source_control_operation_contract(operation)

    assert SourceControlPolicyCheck.WORKSPACE_BOUNDARY in contract.required_policy_checks


@pytest.mark.parametrize(
    "operation",
    [
        SourceControlOperation.PUSH,
        SourceControlOperation.CREATE_BRANCH,
        SourceControlOperation.CREATE_CHANGE_REQUEST,
        SourceControlOperation.UPDATE_CHANGE_REQUEST,
    ],
)
def test_remote_provider_operations_require_secret_scope_boundary(operation):
    contract = get_source_control_operation_contract(operation)

    assert SourceControlPolicyCheck.SECRET_SCOPE_BOUND in contract.required_policy_checks


def test_repository_ref_rejects_credentialed_remote_url():
    with pytest.raises(SourceControlContractError, match="credentialed URLs"):
        SourceControlRepositoryRef(
            provider=SourceControlProvider.GITHUB,
            repository="service-api",
            owner="risk",
            remote_url="https://user:secret@github.example/risk/service-api.git",
        )


@pytest.mark.parametrize(
    "unsafe_inputs",
    [
        {"token": "abc"},
        {"github_token": "abc"},
        {"headers": {"Authorization": "Bearer abc"}},
        {"argv": ["git", "push"]},
        {"command": "git push origin main"},
        {"remote_url": "https://user:secret@bitbucket.example/scm/PROJ/repo.git"},
    ],
)
def test_operation_request_rejects_credentials_and_raw_commands(unsafe_inputs):
    repository = SourceControlRepositoryRef(
        provider="bitbucket",
        project_key="PROJ",
        repository="service-api",
        remote_url="https://bitbucket.example/scm/PROJ/service-api.git",
    )

    with pytest.raises(SourceControlContractError):
        SourceControlOperationRequest(
            operation=SourceControlOperation.PUSH,
            provider=SourceControlProvider.BITBUCKET,
            project_ids=("project-1",),
            repository=repository,
            actor_id="user-1",
            session_id="session-1",
            inputs=unsafe_inputs,
        )


def test_operation_result_rejects_secret_bearing_evidence():
    with pytest.raises(SourceControlContractError):
        SourceControlOperationResult(
            operation=SourceControlOperation.PUSH,
            provider=SourceControlProvider.BITBUCKET,
            status="failed",
            evidence={"stderr": "fatal: https://user:secret@bitbucket.example/scm/PROJ/repo.git"},
        )


def test_operation_request_normalizes_safe_provider_and_project_scope():
    request = SourceControlOperationRequest(
        operation="read_file",
        provider="github",
        project_ids=(" project-1 ", "", "project-2"),
        repository=SourceControlRepositoryRef(
            provider="github",
            owner="risk",
            repository="service-api",
            remote_url="https://github.example/risk/service-api.git",
        ),
        inputs={"path": "README.md", "ref": "main"},
    )

    assert request.operation == SourceControlOperation.READ_FILE
    assert request.provider == SourceControlProvider.GITHUB
    assert request.project_ids == ("project-1", "project-2")
    assert request.repository is not None
    assert request.repository.display_name == "risk/service-api"
