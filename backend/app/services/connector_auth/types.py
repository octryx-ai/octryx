"""The closed authentication modes and schemes of the Atlassian and ServiceNow connectors, as stored in a connection's
``<product>_auth_mode`` / ``servicenow_auth_mode`` field."""

from typing import Literal

AtlassianProduct = Literal["confluence", "jira", "bitbucket"]
AtlassianAuthMode = Literal["cloud_api_token", "basic", "bearer_pat", "oidc_client_credentials"]
AtlassianScheme = Literal["basic", "bearer", "oidc"]
ServiceNowAuthMode = Literal["oidc_client_credentials", "bearer_token", "basic", "oauth_password"]
ServiceNowScheme = Literal["oidc", "oauth_password", "bearer", "basic"]

__all__ = ["AtlassianAuthMode", "AtlassianProduct", "AtlassianScheme", "ServiceNowAuthMode", "ServiceNowScheme"]
