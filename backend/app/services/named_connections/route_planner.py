"""Which connection(s) a connector tool call runs on, planned before anything runs.

A tool several connectors serve (``ConnectorDescriptor.shared_tools``, e.g. CI logs) belongs to the connector
its ``provider`` argument names; without one, and with named connections of any of them, it is refused.

The plan is pure (no session, no secret), so the policy decisions (classification, Cedar) see
the connection ids a call will use (:attr:`RoutePlan.connection_ids`) and ``tool_routing.routed_execute``
executes exactly this plan. For a tool of a descriptor connector (``descriptors/``):

1. routes that lost their type refuse every call (``named_connection_routes_unavailable``);
2. a Workspace without named connections for the connector passes the call through; an explicit
   ``connection`` other than ``default`` is refused there (``connection_unknown``), and so is a key the
   default entry does not declare when it declares one (``default_key_fields``, e.g. another cluster than
   its ``k8s_context``: ``connection_not_configured_for_scope``);
3. an explicit ``connection`` (a named connection's id, its name, or ``default``) runs the call on that
   connection: a name two connections share (a Workspace and a global one) is refused with both ids
   (``connection_ambiguous``), an unknown one with the candidates (``connection_unknown``), and a key the
   call names that this connection does not serve with ``connection_scope_mismatch`` (never another
   connection's credential). A fan-out search with an explicit connection runs on that connection only;
4. a call naming keys runs on the one connection serving them all (``scope_spans_connections`` for two,
   ``connection_not_configured_for_scope`` for none);
5. a call without a key: a fan-out search runs once per connection; otherwise the descriptor's
   ``unscoped`` rule: ``default`` runs on the default connection (its allowlist without the bound keys)
   while that default is usable. Otherwise (``single``, or a ``default`` rule whose default entry has no
   target, e.g. a Workspace served only by named connections) the call runs on the one usable candidate
   (a named connection of the Workspace, then the global ones, then a usable default); several candidates
   are refused with the list in that order (``connection_ambiguous``), none with
   ``connection_not_configured_for_scope``: the call must then name its key or its connection.

Then the grants of the planned connections apply (``connection_gate.gate_plan``): a disabled or
unavailable connection refuses every use, the agent tools level refuses tool calls (``off``; ``read`` for a
write-risk tool), a fan-out skips such connections; a key two connections of the same precedence bind is refused
(``connection_ambiguous``, ``needs_configuration``) before anything is chosen.

:func:`plan_connector` is the same plan for a platform service that is not a tool call (a lookup, a write-back,
a health check): the connector, the keys and an optional explicit connection.
"""

from __future__ import annotations

from .connection_gate import STATE_NEEDS_CONFIGURATION, gate_plan, target_refusal
from .contract import DEFAULT_CONNECTION_NAME, require_descriptor, scope_key
from .descriptor import UNSCOPED_DEFAULT, ConnectorDescriptor
from .descriptors import descriptor_for_tool, shared_claimants
from .resolver import connection_config, connection_name, connection_ref, default_allows
from .route_plan import (
    CONNECTION_PARAM,
    REASON_CONNECTION_AMBIGUOUS,
    REASON_CONNECTION_SCOPE_MISMATCH,
    REASON_CONNECTION_UNKNOWN,
    RoutePlan,
    candidates,
    clean_text,
    refusal,
    scope_keys,
    usable,
)
from .routes_model import (
    REASON_NOT_CONFIGURED_FOR_SCOPE,
    REASON_ROUTES_UNAVAILABLE,
    REASON_SCOPE_SPANS_CONNECTIONS,
    NamedConnectionRoutes,
    ResolvedNamedConnection,
    routes_of,
)

PROVIDER_PARAM = "provider"


def _serves(
    descriptor: ConnectorDescriptor, routes: NamedConnectionRoutes, base: dict,
    connection: ResolvedNamedConnection | None, key: str,
) -> bool:
    tool = descriptor.connector
    if connection is not None:
        found = routes.match(tool, key)
        return found is not None and found.id == connection.id
    return routes.match(tool, key) is None and default_allows(tool, connection_config(base, tool, routes, None), key)


def _explicit(
    descriptor: ConnectorDescriptor, routes: NamedConnectionRoutes, base: dict, wanted: str, keys: tuple[str, ...]
) -> RoutePlan:
    tool = descriptor.connector
    if wanted.lower() == DEFAULT_CONNECTION_NAME:
        chosen: ResolvedNamedConnection | None = None
    else:
        matches = [c for c in routes.of(tool) if c.id == wanted] or [
            c for c in routes.of(tool) if c.name.lower() == wanted.lower()
        ]
        if len(matches) != 1:
            code = REASON_CONNECTION_AMBIGUOUS if matches else REASON_CONNECTION_UNKNOWN
            text = ("Several connections have this name; name the connection by its id." if matches
                    else "No connection of this Workspace has this id or name.")
            return RoutePlan(descriptor, refusal=refusal(code, tool, text, candidates=candidates(routes, tool)))
        chosen = matches[0]
    outside = [key for key in keys if not _serves(descriptor, routes, base, chosen, key)]
    if outside:
        return RoutePlan(descriptor, refusal=refusal(
            REASON_CONNECTION_SCOPE_MISMATCH, tool,
            "The named connection does not serve the requested scope; nothing ran.",
            **{"connection": connection_name(chosen), "connection_id": connection_ref(chosen)}, scopes=outside,
        ))
    return RoutePlan(descriptor, targets=(chosen,), keys=keys)


def _by_keys(
    descriptor: ConnectorDescriptor, routes: NamedConnectionRoutes, base: dict, keys: tuple[str, ...]
) -> RoutePlan:
    tool = descriptor.connector
    served = {key: routes.match(tool, key) for key in keys}
    # Told apart by id: a Workspace and a global connection may share a name, never an account.
    if len({connection_ref(connection) for connection in served.values()}) > 1:
        names = sorted({connection_name(connection) for connection in served.values()})
        return RoutePlan(descriptor, refusal=refusal(
            REASON_SCOPE_SPANS_CONNECTIONS, tool,
            "The requested scopes are served by different connections; ask for one scope per call.",
            scopes=list(keys), connections=names,
        ))
    connection = next(iter(served.values()))
    if connection is None:
        default = connection_config(base, tool, routes, None)
        if not (usable(descriptor, default) and all(default_allows(tool, default, key) for key in keys)):
            return RoutePlan(descriptor, refusal=refusal(
                REASON_NOT_CONFIGURED_FOR_SCOPE, tool,
                "No connection of this Workspace serves the requested scope.", scopes=list(keys),
            ))
    return RoutePlan(descriptor, targets=(connection,), keys=keys)


def _unscoped(descriptor: ConnectorDescriptor, routes: NamedConnectionRoutes, base: dict, tool_name: str) -> RoutePlan:
    tool = descriptor.connector
    default_usable = usable(descriptor, connection_config(base, tool, routes, None))
    if tool_name in descriptor.fan_out_tools:
        targets: list[ResolvedNamedConnection | None] = [*routes.of(tool)]
        if default_usable:
            targets.append(None)
        return RoutePlan(descriptor, targets=tuple(targets), fan_out=True)
    if descriptor.unscoped == UNSCOPED_DEFAULT and default_usable:
        return RoutePlan(descriptor, targets=(None,))
    # Routes list the Workspace's own connections first, then the global ones (``resolver.workspace_routes``).
    served: list[ResolvedNamedConnection | None] = [
        c for c in routes.of(tool)
        if usable(descriptor, c.config) and target_refusal(routes, tool, c, tool_name) is None
    ]
    if default_usable:
        served.append(None)
    if len(served) == 1:
        return RoutePlan(descriptor, targets=(served[0],))
    binding = descriptor.binding
    if not served:
        return RoutePlan(descriptor, refusal=refusal(
            REASON_NOT_CONFIGURED_FOR_SCOPE, tool,
            f"No {descriptor.label} connection of this Workspace has a target; nothing ran.",
            candidates=candidates(routes, tool),
        ))
    return RoutePlan(descriptor, refusal=refusal(
        REASON_CONNECTION_AMBIGUOUS, tool,
        f"Several {descriptor.label} connections could serve this call; name the {binding.label} or the "
        f"connection ('{CONNECTION_PARAM}': an id or name from the candidates).",
        candidates=candidates(routes, tool),
    ))


def _single_default(descriptor: ConnectorDescriptor, base: dict, keys: tuple[str, ...]) -> RoutePlan:
    """Without named connections: the call passes through, unless it names a key the default does not declare.

    Only for a descriptor whose default entry declares its key (``default_key_fields``: a Kubernetes context,
    an AWS account id, ...): a call naming another key would otherwise run on the default's account. A default
    that declares no key keeps today's behaviour (it serves whatever its credential reaches).
    """
    declared = descriptor.default_keys(base) if descriptor.default_key_fields else None
    outside = [key for key in keys if declared and key not in declared]
    if outside:
        # The declared key value(s) (a context, account or project id, never a secret field's value) let the
        # model retry with the right one.
        served = _declared_without_secrets(descriptor, base, declared)
        served_text = f": {', '.join(served)}" if served else ""
        return RoutePlan(descriptor, refusal=refusal(
            REASON_NOT_CONFIGURED_FOR_SCOPE, descriptor.connector,
            f"The {descriptor.label} connection of this Workspace serves another {descriptor.binding.label}"
            f"{served_text}; nothing ran.",
            connection=DEFAULT_CONNECTION_NAME, connection_id=DEFAULT_CONNECTION_NAME, scopes=outside,
            served_scopes=served,
        ))
    return RoutePlan(descriptor, passthrough=True)


def _declared_without_secrets(descriptor: ConnectorDescriptor, base: dict, declared: frozenset[str]) -> list[str]:
    """The default's declared keys, minus any value a secret field of the connector also holds."""
    secrets = {
        descriptor.scope_key(base.get(name)) for name in descriptor.secret_fields if clean_text(base.get(name))
    }
    return sorted(key for key in declared if key not in secrets)


def plan_route(tool_name: str, params: dict | None, base: dict | None, *, agent_tool: bool = True) -> RoutePlan:
    """The plan of one call over the merged config ``base`` (see the module doc).

    ``agent_tool`` False: a published workflow's own platform action. The connection's agent tools level
    governs agents, not the platform's own steps; disabled or unavailable connections still refuse."""
    args = params if isinstance(params, dict) else {}
    config = base if isinstance(base, dict) else {}
    routes = routes_of(config)
    descriptor = descriptor_for_tool(tool_name)
    if descriptor is None:
        claimants = shared_claimants(tool_name)
        provider = clean_text(args.get(PROVIDER_PARAM)).lower()
        descriptor = next((item for item in claimants if item.connector == provider), None)
        if descriptor is None:
            unnamed = not provider  # a provider of another connector (e.g. azure_devops) is not routed here
            if claimants and unnamed and (routes.unavailable or any(routes.has(item.connector) for item in claimants)):
                names = ", ".join(item.connector for item in claimants)
                return RoutePlan(claimants[0], refusal=refusal(
                    REASON_CONNECTION_AMBIGUOUS, claimants[0].connector,
                    f"Several connectors and connections could serve this call; name the {PROVIDER_PARAM} "
                    f"({names}) and, if needed, the connection.",
                    candidates=[{"provider": item.connector} for item in claimants],
                ))
            return RoutePlan(None, passthrough=True)
    return gate_plan(_plan(descriptor, config, scope_keys(descriptor, tool_name, args),
                           clean_text(args.get(CONNECTION_PARAM)), tool_name), config, tool_name if agent_tool else "")


def _plan(
    descriptor: ConnectorDescriptor, config: dict, keys: tuple[str, ...], wanted: str, tool_name: str
) -> RoutePlan:
    tool = descriptor.connector
    routes = routes_of(config)
    if routes.unavailable:
        return RoutePlan(descriptor, refusal=refusal(
            REASON_ROUTES_UNAVAILABLE, tool, "The connections of this Workspace could not be resolved; nothing ran."
        ))
    if not routes.has(tool):
        if wanted and wanted.lower() != DEFAULT_CONNECTION_NAME:
            return RoutePlan(descriptor, refusal=refusal(
                REASON_CONNECTION_UNKNOWN, tool, "No connection of this Workspace has this id or name.",
                candidates=candidates(routes, tool),
            ))
        return _single_default(descriptor, config, keys)
    ambiguous = routes.ambiguous_keys(tool, keys)
    if ambiguous:
        return RoutePlan(descriptor, refusal=refusal(
            REASON_CONNECTION_AMBIGUOUS, tool, "Two connections of the same precedence serve the requested scope; "
            "an admin must bind it to one of them. Nothing ran.", state=STATE_NEEDS_CONFIGURATION, scopes=ambiguous,
            candidates=candidates(routes, tool),
        ))
    if wanted:
        return _explicit(descriptor, routes, config, wanted, keys)
    if keys:
        return _by_keys(descriptor, routes, config, keys)
    return _unscoped(descriptor, routes, config, tool_name)


def plan_connector(
    connector: str, base: dict | None, *, keys: tuple[str, ...] = (), explicit_connection: str | None = None
) -> RoutePlan:
    """The plan of a platform service's use of ``connector`` (no tool call): the same rules as a call naming
    ``keys`` (raw binding keys, canonicalised here) and, optionally, an explicit connection id or name."""
    descriptor = require_descriptor(connector)
    canonical = tuple(dict.fromkeys(scope_key(connector, key) for key in keys if clean_text(key)))
    config = base if isinstance(base, dict) else {}
    return gate_plan(_plan(descriptor, config, canonical, clean_text(explicit_connection), ""), config)


def planned_connection_ids(tool_name: str, params: dict | None, base: dict | None) -> tuple[str, ...]:
    """The connection ids a call will use, for policy decisions (``()``: none or refused)."""
    return plan_route(tool_name, params, base).connection_ids


__all__ = ["plan_connector", "plan_route", "planned_connection_ids"]
