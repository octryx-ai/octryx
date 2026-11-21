"""Connector tests that need only the shared httpx module or a session.

``connector_test_service`` dispatches to these tests. The httpx module is passed as the module
object, so a test that patches ``httpx.AsyncClient`` reaches these calls.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.services.connector_test.cloud import (
    test_aws_connection as _test_aws_connection_impl,
)
from app.services.connector_test.cloud import (
    test_azure_connection as _test_azure_connection_impl,
)
from app.services.connector_test.cloud import (
    test_gcp_connection as _test_gcp_connection_impl,
)
from app.services.connector_test.collab import (
    test_bitbucket_connection as _test_bitbucket_connection_impl,
)
from app.services.connector_test.collab import (
    test_confluence_connection as _test_confluence_connection_impl,
)
from app.services.connector_test.collab import (
    test_github_connection as _test_github_connection_impl,
)
from app.services.connector_test.collab import (
    test_jira_connection as _test_jira_connection_impl,
)
from app.services.connector_test.devtools import (
    test_azure_devops_connection as _test_azure_devops_connection_impl,
)
from app.services.connector_test.devtools import (
    test_docker_registry_connection as _test_docker_registry_connection_impl,
)
from app.services.connector_test.devtools import (
    test_linear_connection as _test_linear_connection_impl,
)
from app.services.connector_test.incident import (
    test_argocd_connection as _test_argocd_connection_impl,
)
from app.services.connector_test.incident import (
    test_kubernetes_connection as _test_kubernetes_connection_impl,
)
from app.services.connector_test.incident import (
    test_pagerduty_connection as _test_pagerduty_connection_impl,
)
from app.services.connector_test.incident import (
    test_statuspage_connection as _test_statuspage_connection_impl,
)
from app.services.connector_test.platforms import (
    test_datadog_connection as _test_datadog_connection_impl,
)
from app.services.connector_test.platforms import (
    test_newrelic_connection as _test_newrelic_connection_impl,
)
from app.services.connector_test.platforms import (
    test_outlook_calendar_connection as _test_outlook_calendar_connection_impl,
)
from app.services.connector_test.platforms import (
    test_snyk_connection as _test_snyk_connection_impl,
)
from app.services.connector_test.platforms import (
    test_sonarqube_connection as _test_sonarqube_connection_impl,
)
from app.services.connector_test.platforms import (
    test_splunk_connection as _test_splunk_connection_impl,
)
from app.services.connector_test.platforms import (
    test_vault_connection as _test_vault_connection_impl,
)
from app.services.connector_test.servicenow import (
    test_servicenow_connection as _test_servicenow_connection_impl,
)


async def test_jira_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_jira_connection_impl(config, httpx_module=httpx)


async def test_bitbucket_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_bitbucket_connection_impl(config, httpx_module=httpx)


async def test_github_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_github_connection_impl(config, httpx_module=httpx)


async def test_confluence_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_confluence_connection_impl(config, httpx_module=httpx)


async def test_kubernetes_connection(config: dict[str, Any], *, db: Any = None) -> dict[str, Any]:
    return await _test_kubernetes_connection_impl(config, httpx_module=httpx, db=db)


async def test_pagerduty_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_pagerduty_connection_impl(config, httpx_module=httpx)


async def test_argocd_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_argocd_connection_impl(config, httpx_module=httpx)


async def test_outlook_calendar_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_outlook_calendar_connection_impl(config, httpx_module=httpx)


async def test_vault_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_vault_connection_impl(config, httpx_module=httpx)


async def test_sonarqube_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_sonarqube_connection_impl(config, httpx_module=httpx)


async def test_snyk_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_snyk_connection_impl(config, httpx_module=httpx)


async def test_datadog_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_datadog_connection_impl(config, httpx_module=httpx)


async def test_newrelic_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_newrelic_connection_impl(config, httpx_module=httpx)


async def test_statuspage_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_statuspage_connection_impl(config, httpx_module=httpx)


async def test_docker_registry_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_docker_registry_connection_impl(config, httpx_module=httpx)


async def test_splunk_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_splunk_connection_impl(config, httpx_module=httpx)


async def test_linear_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_linear_connection_impl(config, httpx_module=httpx)


async def test_azure_devops_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_azure_devops_connection_impl(config, httpx_module=httpx)


async def test_aws_connection(config: dict[str, Any], *, db: Any = None) -> dict[str, Any]:
    return await _test_aws_connection_impl(config, db=db)


async def test_azure_connection(config: dict[str, Any], *, db: Any = None) -> dict[str, Any]:
    return await _test_azure_connection_impl(config, db=db)


async def test_gcp_connection(config: dict[str, Any], *, db: Any = None) -> dict[str, Any]:
    return await _test_gcp_connection_impl(config, db=db)


async def test_servicenow_connection(config: dict[str, Any]) -> dict[str, Any]:
    return await _test_servicenow_connection_impl(config, httpx_module=httpx)
