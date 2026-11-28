"""Contract: every outbound connection type is classified in one closed table."""

from __future__ import annotations

import ast
import inspect
import pathlib
import sys

import pytest

from app.services.outbound_egress import ALLOWLISTABLE_CONNECTIONS, CONNECTIONS, connection_rule
from app.services.outbound_egress.connections import _RULES
from app.services.outbound_url_policy import EGRESS_SCOPE_NO_POD_LOCAL as NO_POD_LOCAL
from app.services.outbound_url_policy import EGRESS_SCOPE_PUBLIC_ONLY as PUBLIC_ONLY

APP = pathlib.Path(__file__).resolve().parents[3] / "app"
#: The shared helper modules; a connector binds their HTTP helpers to its own type.
SHARED_HELPER_MODULES = frozenset({"app.tools.connectors.common", "app.tools.connectors.cloud_common"})
HTTP_HELPERS = ("_http_json", "_http_form_json", "_http_response", "_http_text")
#: A helper's own connection parameter, passed through (Source Sync passes its connector kind).
PASS_THROUGH = frozenset({"connection", "connection_kind"})
BINDERS = ("connection_http_json", "connection_http_form_json", "connection_http_response", "connection_http_text")

#: (scope, private-host allowlist) per connection type. Changing a row is a reviewed decision.
EXPECTED = {
    # SaaS with an on-prem edition
    "jira": (PUBLIC_ONLY, True),
    "confluence": (PUBLIC_ONLY, True),
    "bitbucket": (PUBLIC_ONLY, True),
    "github": (PUBLIC_ONLY, True),
    "gitlab": (PUBLIC_ONLY, True),
    "servicenow": (PUBLIC_ONLY, True),
    "azure_devops": (PUBLIC_ONLY, True),
    "sonarqube": (PUBLIC_ONLY, True),
    # the signed outbound webhook delivery (an on-prem receiver only through the allowlist)
    "outbound_webhook": (PUBLIC_ONLY, True),
    # an admin-defined REST API (custom REST connector)
    "custom_rest": (PUBLIC_ONLY, True),
    # SaaS only
    "datadog": (PUBLIC_ONLY, False),
    "newrelic": (PUBLIC_ONLY, False),
    "pagerduty": (PUBLIC_ONLY, False),
    "opsgenie": (PUBLIC_ONLY, False),
    "statuspage": (PUBLIC_ONLY, False),
    "linear": (PUBLIC_ONLY, False),
    "notion": (PUBLIC_ONLY, False),
    "snyk": (PUBLIC_ONLY, False),
    "microsoft_graph": (PUBLIC_ONLY, False),
    "azure": (PUBLIC_ONLY, False),
    "gcp": (PUBLIC_ONLY, False),
    # a public Git repository, credential-free (Source Sync git_repository)
    "git_repository": (PUBLIC_ONLY, False),
    # the uncredentialed web fetch
    "public_web": (PUBLIC_ONLY, False),
    # private-network systems
    "kubernetes": (NO_POD_LOCAL, False),
    "vault": (NO_POD_LOCAL, False),
    "argocd": (NO_POD_LOCAL, False),
    "grafana": (NO_POD_LOCAL, False),
    "splunk": (NO_POD_LOCAL, False),
    "elasticsearch": (NO_POD_LOCAL, False),
    "container_registry": (NO_POD_LOCAL, False),
}


def _sources() -> dict[pathlib.Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in APP.rglob("*.py")}


def _named_connections(tree: ast.AST) -> list[ast.expr]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", "")
        if name in ("egress_transport", "PinnedEgressTransport", *BINDERS) and node.args:
            found.append(node.args[0])
        if name in NAMED_CONNECTION_CALLS:
            continue  # ``connection=`` there names a named connection, not an egress rule
        found += [keyword.value for keyword in node.keywords if keyword.arg == "connection"]
    return found


#: Calls whose ``connection=`` is a named connection's name (``named_connections.route_plan.refusal``).
NAMED_CONNECTION_CALLS = frozenset({"refusal"})


def test_the_connection_table_is_closed_and_exact():
    assert {name: (rule.scope, rule.private_allowlist) for name, rule in _RULES.items()} == EXPECTED
    assert set(CONNECTIONS) == set(EXPECTED)
    assert ALLOWLISTABLE_CONNECTIONS == tuple(sorted(name for name, (_, allow) in EXPECTED.items() if allow))
    for name, rule in _RULES.items():
        assert rule.kind == ("private_network" if rule.scope == NO_POD_LOCAL else rule.kind), name
    assert not any("private_network_integration" in text for text in _sources().values())


def test_the_connector_helpers_have_no_default_connection():
    tree = ast.parse((APP / "tools" / "connectors" / "common.py").read_text(encoding="utf-8"))
    helpers = {node.name: node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)}
    for helper in HTTP_HELPERS:
        arguments = helpers[helper].args
        index = [argument.arg for argument in arguments.kwonlyargs].index("connection")
        assert arguments.kw_defaults[index] is None, helper


def test_every_client_names_a_classified_connection_constant():
    import app.services.outbound_egress as egress

    unclassified = []
    for path, text in _sources().items():
        if "services/outbound_egress/" in str(path):
            continue
        for argument in _named_connections(ast.parse(text)):
            if isinstance(argument, ast.Name) and argument.id.startswith("CONNECTION_"):
                value = getattr(egress, argument.id, None)
                if value is None or value not in _RULES:
                    unclassified.append((str(path.relative_to(APP)), argument.id))
            elif not (isinstance(argument, ast.Name) and argument.id in PASS_THROUGH):
                # Only a named constant, or a helper's own connection parameter passed through.
                unclassified.append((str(path.relative_to(APP)), ast.unparse(argument)))
    assert unclassified == []
    # Source Sync passes its connector kind through; every kind is a classified type.
    from app.models.project.knowledge_source_sync import CONNECTOR_KINDS

    assert CONNECTOR_KINDS <= set(_RULES)


def _module_connections(module) -> set[str]:
    connections = {
        getattr(getattr(module, helper, None), "egress_connection", None) for helper in HTTP_HELPERS
    } - {None}
    try:
        tree = ast.parse(inspect.getsource(module))
    except (OSError, TypeError):
        return connections
    for argument in _named_connections(tree):
        if isinstance(argument, ast.Name) and isinstance(getattr(module, argument.id, None), str):
            connections.add(getattr(module, argument.id))
    return connections


def _makes_http_calls(module) -> bool:
    try:
        source = inspect.getsource(module)
    except (OSError, TypeError):
        return False
    return any(f"{helper}(" in source for helper in HTTP_HELPERS) or "egress_transport(" in source


@pytest.mark.parametrize("package", ["app.tools.connectors."])
def test_every_connector_tool_resolves_to_a_classified_connection(package):
    from app.tools.registry import TOOL_REGISTRY

    unresolved = []
    for tool_name, tool in sorted(TOOL_REGISTRY.items()):
        module = sys.modules[type(tool).__module__]
        if not module.__name__.startswith(package):
            continue
        # The tool's module and the connector modules it delegates to (``incidents`` -> PagerDuty, ...).
        related = [module] + [
            value
            for value in (sys.modules.get(getattr(obj, "__module__", "")) for obj in vars(module).values())
            if value is not None
            and value.__name__.startswith(package)
            and value.__name__ not in SHARED_HELPER_MODULES
            and value is not module
        ]
        if not any(_makes_http_calls(candidate) for candidate in related):
            continue  # an SDK or CLI connector (AWS, Terraform, Ansible, LDAP, ...)
        connections = set().union(*(_module_connections(candidate) for candidate in related))
        if not connections or any(connection_rule(name) is None for name in connections):
            unresolved.append(tool_name)
    assert unresolved == []
