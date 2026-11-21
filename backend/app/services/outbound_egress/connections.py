"""One egress rule per connection type: which addresses an outbound client may reach.

Every outbound client names its connection type, and the type alone decides the rule, so the
chat tools, the connection tests, Source Sync, design-delivery sync and the SCM services apply
the same rule to the same connection. The table is closed: each connection type is classified
here, and an unknown type refuses at client construction (``UnknownEgressConnectionError``);
there is no default rule and no catch-all type.

* **SaaS** (a vendor-hosted endpoint on the public internet): the ``public_only`` scope. Where the
  product also ships an on-prem edition (Jira/Confluence Data Center, Bitbucket and GitHub
  Enterprise Server, GitLab self-managed, ServiceNow, Azure DevOps Server, SonarQube Server),
  an instance on a private address is reachable only through the admin-governed private-host
  allowlist of its type (``private_hosts.py``); pod-local and metadata addresses never are.
* **Private-network systems** (Kubernetes, Vault, Argo CD, Grafana, Splunk, Elasticsearch, a
  self-hosted container registry): the ``no_pod_local`` scope. They normally live in the private
  network; the pod and metadata stay refused.
* **A custom REST API** (``custom_rest``, an admin-defined API of the custom REST connector): ``public_only``; an
  on-prem API is reachable only through the admin-governed private-host allowlist, like a SaaS with an on-prem edition.
* **The uncredentialed public web fetch** (``public_web.py``): ``public_only``, no allowlist.
* **A public Git repository** (Source Sync ``git_repository``): ``public_only``, no allowlist; only
  the public, credential-free path exists.
* **An outbound webhook receiver** (``outbound_webhook``, the signed event delivery): ``public_only``;
  an on-prem receiver is reachable only through the admin-governed private-host allowlist.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..outbound_url_policy import EGRESS_SCOPE_NO_POD_LOCAL, EGRESS_SCOPE_PUBLIC_ONLY

# SaaS with an on-prem edition (public_only + private-host allowlist).
CONNECTION_JIRA = "jira"
CONNECTION_CONFLUENCE = "confluence"
CONNECTION_BITBUCKET = "bitbucket"
CONNECTION_GITHUB = "github"
CONNECTION_GITLAB = "gitlab"
CONNECTION_SERVICENOW = "servicenow"
CONNECTION_AZURE_DEVOPS = "azure_devops"
CONNECTION_SONARQUBE = "sonarqube"
# A signed event delivery to an admin-entered URL (public_only + private-host allowlist).
CONNECTION_OUTBOUND_WEBHOOK = "outbound_webhook"
# An admin-defined REST API (custom REST connector): public, or on-prem through the private-host allowlist.
CONNECTION_CUSTOM_REST = "custom_rest"
# SaaS only (public_only).
CONNECTION_DATADOG = "datadog"
CONNECTION_NEWRELIC = "newrelic"
CONNECTION_PAGERDUTY = "pagerduty"
CONNECTION_OPSGENIE = "opsgenie"
CONNECTION_STATUSPAGE = "statuspage"
CONNECTION_LINEAR = "linear"
CONNECTION_NOTION = "notion"
CONNECTION_SNYK = "snyk"
CONNECTION_MICROSOFT_GRAPH = "microsoft_graph"
CONNECTION_AZURE = "azure"
CONNECTION_GCP = "gcp"
CONNECTION_PUBLIC_WEB = "public_web"
# A public Git host read without a credential (Source Sync ``git_repository``).
CONNECTION_GIT_REPOSITORY = "git_repository"
# Private-network systems (no_pod_local).
CONNECTION_KUBERNETES = "kubernetes"
CONNECTION_VAULT = "vault"
CONNECTION_ARGOCD = "argocd"
CONNECTION_GRAFANA = "grafana"
CONNECTION_SPLUNK = "splunk"
CONNECTION_ELASTICSEARCH = "elasticsearch"
CONNECTION_CONTAINER_REGISTRY = "container_registry"

KIND_SAAS = "saas"
KIND_PRIVATE_NETWORK = "private_network"
KIND_PUBLIC_WEB = "public_web"


@dataclass(frozen=True)
class EgressConnectionRule:
    connection: str
    scope: str
    private_allowlist: bool
    kind: str


def _saas(name: str, *, on_prem_edition: bool) -> EgressConnectionRule:
    return EgressConnectionRule(name, EGRESS_SCOPE_PUBLIC_ONLY, private_allowlist=on_prem_edition, kind=KIND_SAAS)


def _private_network(name: str) -> EgressConnectionRule:
    return EgressConnectionRule(name, EGRESS_SCOPE_NO_POD_LOCAL, private_allowlist=False, kind=KIND_PRIVATE_NETWORK)


_RULES: dict[str, EgressConnectionRule] = {
    rule.connection: rule
    for rule in (
        *(
            _saas(name, on_prem_edition=True)
            for name in (
                CONNECTION_JIRA,
                CONNECTION_CONFLUENCE,
                CONNECTION_BITBUCKET,
                CONNECTION_GITHUB,
                CONNECTION_GITLAB,
                CONNECTION_SERVICENOW,
                CONNECTION_AZURE_DEVOPS,
                CONNECTION_SONARQUBE,
                CONNECTION_OUTBOUND_WEBHOOK,
                CONNECTION_CUSTOM_REST,
            )
        ),
        *(
            _saas(name, on_prem_edition=False)
            for name in (
                CONNECTION_DATADOG,
                CONNECTION_NEWRELIC,
                CONNECTION_PAGERDUTY,
                CONNECTION_OPSGENIE,
                CONNECTION_STATUSPAGE,
                CONNECTION_LINEAR,
                CONNECTION_NOTION,
                CONNECTION_SNYK,
                CONNECTION_MICROSOFT_GRAPH,
                CONNECTION_AZURE,
                CONNECTION_GCP,
                CONNECTION_GIT_REPOSITORY,
            )
        ),
        EgressConnectionRule(
            CONNECTION_PUBLIC_WEB, EGRESS_SCOPE_PUBLIC_ONLY, private_allowlist=False, kind=KIND_PUBLIC_WEB
        ),
        *(
            _private_network(name)
            for name in (
                CONNECTION_KUBERNETES,
                CONNECTION_VAULT,
                CONNECTION_ARGOCD,
                CONNECTION_GRAFANA,
                CONNECTION_SPLUNK,
                CONNECTION_ELASTICSEARCH,
                CONNECTION_CONTAINER_REGISTRY,
            )
        ),
    )
}

#: Every classified connection type, in a stable order.
CONNECTIONS: tuple[str, ...] = tuple(sorted(_RULES))
#: Connection types an admin may give on-prem private hosts to, in a stable order.
ALLOWLISTABLE_CONNECTIONS: tuple[str, ...] = tuple(
    sorted(name for name, rule in _RULES.items() if rule.private_allowlist)
)


class UnknownEgressConnectionError(ValueError):
    """A client named a connection type that has no egress rule."""


def connection_rule(connection: str) -> EgressConnectionRule:
    rule = _RULES.get(str(connection or ""))
    if rule is None:
        raise UnknownEgressConnectionError("unknown_egress_connection")
    return rule


__all__ = [
    "ALLOWLISTABLE_CONNECTIONS",
    "CONNECTIONS",
    "CONNECTION_ARGOCD",
    "CONNECTION_AZURE",
    "CONNECTION_AZURE_DEVOPS",
    "CONNECTION_BITBUCKET",
    "CONNECTION_CONFLUENCE",
    "CONNECTION_CONTAINER_REGISTRY",
    "CONNECTION_CUSTOM_REST",
    "CONNECTION_DATADOG",
    "CONNECTION_ELASTICSEARCH",
    "CONNECTION_GCP",
    "CONNECTION_GIT_REPOSITORY",
    "CONNECTION_GITHUB",
    "CONNECTION_GITLAB",
    "CONNECTION_GRAFANA",
    "CONNECTION_JIRA",
    "CONNECTION_KUBERNETES",
    "CONNECTION_LINEAR",
    "CONNECTION_MICROSOFT_GRAPH",
    "CONNECTION_NEWRELIC",
    "CONNECTION_NOTION",
    "CONNECTION_OPSGENIE",
    "CONNECTION_OUTBOUND_WEBHOOK",
    "CONNECTION_PAGERDUTY",
    "CONNECTION_PUBLIC_WEB",
    "CONNECTION_SERVICENOW",
    "CONNECTION_SNYK",
    "CONNECTION_SONARQUBE",
    "CONNECTION_SPLUNK",
    "CONNECTION_STATUSPAGE",
    "CONNECTION_VAULT",
    "EgressConnectionRule",
    "KIND_PRIVATE_NETWORK",
    "KIND_PUBLIC_WEB",
    "KIND_SAAS",
    "UnknownEgressConnectionError",
    "connection_rule",
]
