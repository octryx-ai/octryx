from __future__ import annotations

import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.connector_test.failure import exception_failure
from app.services.connector_test.infra import (
    test_ansible_connection as _test_ansible_connection_impl,
)
from app.services.connector_test.infra import (
    test_helm_connection as _test_helm_connection_impl,
)
from app.services.connector_test.infra import (
    test_ldap_connection as _test_ldap_connection_impl,
)
from app.services.connector_test.infra import (
    test_terraform_connection as _test_terraform_connection_impl,
)
from app.services.connector_test.runtime import (
    binary_is_available_for_runtime as _binary_is_available_for_runtime_impl,
)
from app.services.connector_test.runtime import (
    run_runtime_probe as _run_runtime_probe_impl,
)
from app.services.connector_test.scope_check import check_scopes, with_scope_check
from app.services.connector_test.wrappers import (
    test_argocd_connection,
    test_aws_connection,
    test_azure_connection,
    test_azure_devops_connection,
    test_bitbucket_connection,
    test_confluence_connection,
    test_datadog_connection,
    test_docker_registry_connection,
    test_gcp_connection,
    test_github_connection,
    test_jira_connection,
    test_kubernetes_connection,
    test_linear_connection,
    test_newrelic_connection,
    test_outlook_calendar_connection,
    test_pagerduty_connection,
    test_servicenow_connection,
    test_snyk_connection,
    test_sonarqube_connection,
    test_splunk_connection,
    test_statuspage_connection,
    test_vault_connection,
)

from .execution_runtime import execute_with_runtime, resolve_execution_runtime_config


async def _binary_is_available_for_runtime(config: dict[str, Any], binary: str) -> bool:
    return await _binary_is_available_for_runtime_impl(
        config,
        binary,
        resolve_runtime_config_fn=resolve_execution_runtime_config,
        which_fn=shutil.which,
    )


async def _run_runtime_probe(
    *,
    config: dict[str, Any],
    command: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout_sec: int = 30,
) -> tuple[int, str, str, dict[str, Any]]:
    return await _run_runtime_probe_impl(
        config=config,
        command=command,
        cwd=cwd,
        env=env,
        timeout_sec=timeout_sec,
        execute_with_runtime_fn=execute_with_runtime,
    )


# The runtime-backed tests stay in this module: they read ``execute_with_runtime`` and
# ``resolve_execution_runtime_config`` from here at call time, which is where tests patch them.
async def test_terraform_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_terraform_connection_impl(
        config,
        resolve_runtime_config_fn=resolve_execution_runtime_config,
        execute_with_runtime_fn=execute_with_runtime,
        which_fn=shutil.which,
    )


async def test_ldap_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_ldap_connection_impl(
        config,
        resolve_runtime_config_fn=resolve_execution_runtime_config,
        execute_with_runtime_fn=execute_with_runtime,
        which_fn=shutil.which,
    )


async def test_ansible_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_ansible_connection_impl(
        config,
        resolve_runtime_config_fn=resolve_execution_runtime_config,
        execute_with_runtime_fn=execute_with_runtime,
        which_fn=shutil.which,
    )


async def test_helm_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_helm_connection_impl(
        config,
        resolve_runtime_config_fn=resolve_execution_runtime_config,
        execute_with_runtime_fn=execute_with_runtime,
        which_fn=shutil.which,
    )


ConnectorTestFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


CONNECTOR_TESTS: dict[str, ConnectorTestFn] = {
    "jira": test_jira_connection,
    "bitbucket": test_bitbucket_connection,
    "github": test_github_connection,
    "confluence": test_confluence_connection,
    "kubernetes": test_kubernetes_connection,
    "pagerduty": test_pagerduty_connection,
    "argocd": test_argocd_connection,
    "terraform": test_terraform_connection,
    "ldap": test_ldap_connection,
    "outlook_calendar": test_outlook_calendar_connection,
    "vault": test_vault_connection,
    "sonarqube": test_sonarqube_connection,
    "snyk": test_snyk_connection,
    "ansible": test_ansible_connection,
    "datadog": test_datadog_connection,
    "newrelic": test_newrelic_connection,
    "aws": test_aws_connection,
    "azure": test_azure_connection,
    "gcp": test_gcp_connection,
    "statuspage": test_statuspage_connection,
    "helm": test_helm_connection,
    "docker_registry": test_docker_registry_connection,
    "splunk": test_splunk_connection,
    "linear": test_linear_connection,
    "azure_devops": test_azure_devops_connection,
    "servicenow": test_servicenow_connection,
}


# The tests that run tool helpers through a tool context: they get the caller's session, so the helpers
# resolve runtimes and secrets as in a real call instead of failing closed without one.
SESSION_CONNECTOR_TESTS = frozenset({"kubernetes", "aws", "azure", "gcp"})


async def run_connector_connection_test(
    tool_name: str, config: dict[str, Any], *, db: AsyncSession | None = None, scope_check: bool = False
) -> dict[str, Any]:
    """The connector's test; ``scope_check`` (admin tests only): configured versus visible keys."""
    handler = CONNECTOR_TESTS.get(tool_name)
    if handler is None:
        # Explicit "no test available": recorded as health ``no_test``, never a breaker failure.
        return {"ok": False, "no_test": True, "summary": f"Connection test is not implemented for {tool_name}."}
    try:
        if tool_name in SESSION_CONNECTOR_TESTS:
            result = await handler(config, db=db)
        else:
            result = await handler(config)
        if scope_check and result.get("ok"):
            result = with_scope_check(result, await check_scopes(tool_name, config, httpx_module=httpx))
        return result
    except Exception as exc:
        return exception_failure(tool_name, exc)


__all__ = [
    "_binary_is_available_for_runtime",
    "_run_runtime_probe",
    "test_terraform_connection",
    "test_ldap_connection",
    "test_ansible_connection",
    "test_helm_connection",
    "SESSION_CONNECTOR_TESTS",
    "run_connector_connection_test",
]
