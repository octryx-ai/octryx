"""Bitbucket source-control contract helpers."""

from __future__ import annotations

from typing import Any

from ...services.source_control import (
    SourceControlOperation,
    SourceControlOperationResult,
    SourceControlProvider,
    SourceControlRepositoryRef,
    get_source_control_operation_contract,
    sanitize_source_control_payload,
)


def bitbucket_repository_ref(project_key: str, repo_slug: str) -> SourceControlRepositoryRef:
    return SourceControlRepositoryRef(
        provider=SourceControlProvider.BITBUCKET,
        project_key=str(project_key or "").strip(),
        repository=str(repo_slug or "").strip(),
    )


def bitbucket_source_control_metadata(
    operation: SourceControlOperation,
    *,
    project_key: str,
    repo_slug: str,
    status: str,
    output: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = get_source_control_operation_contract(operation)
    repository = bitbucket_repository_ref(project_key, repo_slug)
    safe_output = sanitize_source_control_payload(output or {})
    safe_evidence = sanitize_source_control_payload(evidence or {})
    result = SourceControlOperationResult(
        operation=operation,
        provider=SourceControlProvider.BITBUCKET,
        repository=repository,
        status=status,
        output=safe_output,
        evidence=safe_evidence,
    )
    return {
        "contract_version": "source_control.v1",
        "operation": result.operation.value,
        "provider": result.provider.value,
        "repository": repository.display_name,
        "repository_operation": contract.repository_operation,
        "repository_mode": contract.repository_mode.value,
        "mutation": contract.mutation.value,
        "policy_checks": [check.value for check in contract.required_policy_checks],
        "audit_fields": [field.value for field in contract.audit_fields],
        "status": result.status,
        "output": dict(result.output),
        "evidence": dict(result.evidence),
    }


__all__ = ["bitbucket_repository_ref", "bitbucket_source_control_metadata"]
