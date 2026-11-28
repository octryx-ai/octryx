"""The baseline policy set, generated from today's policy sources."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.services.agent_gateway.policy_keys import (
    RULE_COMMAND_ARGUMENT_DENIED,
    RULE_COMMAND_PREFIX_DENIED,
    RULE_COMMAND_REQUIRES_ARGUMENT,
    RULE_PATH_DENIED,
)
from app.services.data_classification.policy_rules import (
    ACCESS_NONE,
    ACCESS_READ,
    CONNECTOR_FAMILIES,
    ClassificationPolicy,
    LevelRules,
)

from ..agent_gateway.policy import GatewayPolicy
from ..data_classification.levels import level_registry
from ..model_gateway.data_policy.classification import DATA_CLASSIFICATION_ORDER
from .cedar_text import GeneratedPolicy, entity, glob_to_like, literal, policy, string_set
from .device_translator import device_level_policies, device_platform_policies, workspace_device_policies
from .schema import (
    ACTION_CALL_MODEL,
    ACTION_CALL_TOOL,
    ACTION_READ_CONNECTOR,
    ACTION_READ_PATH,
    ACTION_RECEIVE_TOOL_RESULT,
    ACTION_RUN_COMMAND,
    ACTION_RUN_ON_DEVICE,
    ACTION_USE_REMOTE_EMBEDDINGS,
    ACTION_USE_RERANKER,
    ACTION_USE_SEAT,
    ACTION_WRITE_CONNECTOR,
    ACTION_WRITE_PATH,
    ENTITY_CONNECTOR_FAMILY,
    ENTITY_WORKSPACE,
    POINT_CLIENT,
    POINT_GATEWAY,
    ROUTE_SEAT,
    SCHEMA_VERSION,
)

FAMILY_SEAT = "seat"
FAMILY_MODEL = "model"
FAMILY_REMOTE = "remote"
FAMILY_TOOL = "tool"
FAMILY_GATEWAY = "gateway"
FAMILY_CONTENT = "content"
FAMILY_DEVICE = "device"
FAMILIES: tuple[str, ...] = (FAMILY_SEAT, FAMILY_MODEL, FAMILY_REMOTE, FAMILY_TOOL, FAMILY_GATEWAY, FAMILY_CONTENT,
                            FAMILY_DEVICE)
SECRETS_POLICY_ID = "platform:secrets-never-leave"

FORBID = "forbid"
PERMIT = "permit"
TOOL_ACTIONS = (ACTION_CALL_TOOL, ACTION_READ_CONNECTOR, ACTION_WRITE_CONNECTOR)
CONNECTOR_ACTIONS = (ACTION_READ_CONNECTOR, ACTION_WRITE_CONNECTOR)
REMOTE_ACTIONS = (ACTION_USE_RERANKER, ACTION_USE_REMOTE_EMBEDDINGS)
CLIENT_TOOL_ACTIONS = (ACTION_RUN_COMMAND, ACTION_READ_PATH, ACTION_WRITE_PATH)
PATH_ACTIONS = (ACTION_READ_PATH, ACTION_WRITE_PATH)
APPROXIMATE_ANNOTATION = "translation"
APPROXIMATE_VALUE = "approximate"

_CLIENT_PATH_TOOLS = ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit")

HAS_CLASSIFICATION = "context.workspace has classification"


def _level(level: str) -> str:
    return f"{HAS_CLASSIFICATION} && context.workspace.classification == {literal(level)}"


def _workspace(workspace_id: str) -> str:
    return f"context.workspace == {entity(ENTITY_WORKSPACE, workspace_id)}"


# --- platform invariants ---------------------------------------------------------------------------------------


def platform_policies(families: Iterable[str] = FAMILIES) -> list[GeneratedPolicy]:
    wanted = set(families)
    policies: list[GeneratedPolicy] = []
    if FAMILY_SEAT in wanted:
        policies += [
            policy("platform:seat-permit", PERMIT, actions=[ACTION_USE_SEAT]),
            policy("platform:seat-classification-unresolved", FORBID, actions=[ACTION_USE_SEAT],
                   unless=[HAS_CLASSIFICATION]),
            policy("platform:seat-workspace-requires-governed-routing", FORBID, actions=[ACTION_USE_SEAT],
                   when=["resource.requires_governed_routing"]),
            policy("platform:seat-mode-forbidden", FORBID, actions=[ACTION_USE_SEAT],
                   unless=['resource.seat_mode == "allowed"']),
        ]
    if FAMILY_MODEL in wanted:
        policies += [
            policy("platform:model-admission-unverified", FORBID, actions=[ACTION_CALL_MODEL],
                   unless=["context.admission_verified"]),
            policy("platform:model-alias-missing", FORBID, actions=[ACTION_CALL_MODEL],
                   when=['resource.alias == ""']),
        ]
    if FAMILY_REMOTE in wanted:
        policies += [
            policy("platform:remote-model-permit", PERMIT, actions=REMOTE_ACTIONS),
            policy("platform:remote-model-classification-unresolved", FORBID, actions=REMOTE_ACTIONS,
                   unless=["context.workspace has classification_rank"]),
            policy("platform:remote-model-class-unknown", FORBID, actions=REMOTE_ACTIONS,
                   unless=["resource has data_policy_rank"]),
            policy("platform:remote-model-class-insufficient", FORBID, actions=REMOTE_ACTIONS,
                   when=["context.workspace has classification_rank", "resource has data_policy_rank",
                         "context.workspace.classification_rank > resource.data_policy_rank"]),
        ]
    if FAMILY_TOOL in wanted:
        policies.append(policy("platform:tool-permit", PERMIT, actions=TOOL_ACTIONS))
    if FAMILY_GATEWAY in wanted:
        policies.append(policy("platform:client-tool-permit", PERMIT, actions=CLIENT_TOOL_ACTIONS))
    if FAMILY_CONTENT in wanted:
        policies += [
            policy(SECRETS_POLICY_ID, FORBID, actions=[ACTION_CALL_MODEL],
                   when=['context.content.detected.contains("secrets")']),
            policy("platform:seat-route-permit", PERMIT, actions=[ACTION_CALL_MODEL],
                   when=[f"context.route == {literal(ROUTE_SEAT)}"]),
            policy("platform:tool-result-permit", PERMIT, actions=[ACTION_RECEIVE_TOOL_RESULT]),
        ]
    if FAMILY_DEVICE in wanted:
        policies += device_platform_policies()
    return policies


# --- the classification policy matrix ---------------------------------------------------------------------------


def seat_level_policies(level: str, *, seat_allowed: bool, requires_governed_routing: bool) -> list[GeneratedPolicy]:
    policies: list[GeneratedPolicy] = []
    if not seat_allowed:
        policies.append(policy(f"classification:{level}:seat-not-allowed", FORBID, actions=[ACTION_USE_SEAT],
                               when=[_level(level)]))
    if requires_governed_routing:
        policies.append(policy(f"classification:{level}:requires-governed-routing", FORBID,
                               actions=[ACTION_USE_SEAT], when=[_level(level)]))
    return policies


def model_level_policies(level: str, allowed_aliases: Iterable[str] | None) -> list[GeneratedPolicy]:
    if allowed_aliases is None:
        return []
    aliases = sorted(set(allowed_aliases))
    conditions = [_level(level)]
    if aliases:  # an empty list admits no alias at this level (and Cedar has no typed empty set literal)
        conditions.append(f"!{string_set(aliases)}.contains(resource.alias)")
    return [policy(f"classification:{level}:model-aliases", FORBID, actions=[ACTION_CALL_MODEL], when=conditions)]


def no_model_policies(level: str, families: Iterable[str] = FAMILIES) -> list[GeneratedPolicy]:
    registry = level_registry()
    this = registry.get(level)
    if this is None or this.models_allowed or not any(
            other.models_allowed and other.rank > this.rank for other in registry.levels):
        return []
    policies: list[GeneratedPolicy] = []
    if FAMILY_MODEL in families:
        policies.append(policy(f"classification:{level}:no-models", FORBID, actions=[ACTION_CALL_MODEL],
                               when=[_level(level)]))
    if FAMILY_REMOTE in families:
        policies.append(policy(f"classification:{level}:no-remote-models", FORBID, actions=REMOTE_ACTIONS,
                               when=[_level(level)]))
    return policies


def remote_level_policies(
    level: str, *, reranker_allowed: bool, remote_embeddings_allowed: bool
) -> list[GeneratedPolicy]:
    policies: list[GeneratedPolicy] = []
    if not reranker_allowed:
        policies.append(policy(f"classification:{level}:reranker-forbidden", FORBID, actions=[ACTION_USE_RERANKER],
                               when=[_level(level)]))
    if not remote_embeddings_allowed:
        policies.append(policy(f"classification:{level}:remote-embeddings-forbidden", FORBID,
                               actions=[ACTION_USE_REMOTE_EMBEDDINGS], when=[_level(level)]))
    return policies


def tool_level_policies(
    level: str, *, connectors: Mapping[str, str], log_masking_required: bool
) -> list[GeneratedPolicy]:
    policies: list[GeneratedPolicy] = []
    if log_masking_required:
        policies.append(policy(f"classification:{level}:log-masking-not-available", FORBID, actions=TOOL_ACTIONS,
                               when=[_level(level), "context.reads_logs"]))
    for family in CONNECTOR_FAMILIES:
        access = connectors.get(family)
        resource = f"resource in {entity(ENTITY_CONNECTOR_FAMILY, family)}"
        if access == ACCESS_NONE:
            policies.append(policy(f"classification:{level}:connector:{family}:none", FORBID,
                                   actions=CONNECTOR_ACTIONS, resource=resource, when=[_level(level)]))
        elif access == ACCESS_READ:
            policies.append(policy(f"classification:{level}:connector:{family}:read-only", FORBID,
                                   actions=[ACTION_WRITE_CONNECTOR], resource=resource, when=[_level(level)]))
    return policies


def level_policies(level: str, rules: LevelRules, families: Iterable[str] = FAMILIES) -> list[GeneratedPolicy]:
    wanted = set(families)
    policies: list[GeneratedPolicy] = []
    if FAMILY_SEAT in wanted:
        policies += seat_level_policies(level, seat_allowed=rules.seat_allowed,
                                        requires_governed_routing=rules.requires_governed_routing)
    if FAMILY_MODEL in wanted:
        policies += model_level_policies(level, rules.allowed_model_aliases)
    if FAMILY_REMOTE in wanted:
        policies += remote_level_policies(level, reranker_allowed=rules.reranker_allowed,
                                          remote_embeddings_allowed=rules.remote_embeddings_allowed)
    if FAMILY_TOOL in wanted:
        connectors = {family: rules.connector_access(family) for family in CONNECTOR_FAMILIES}
        policies += tool_level_policies(level, connectors=connectors,
                                        log_masking_required=rules.log_masking_required)
    if FAMILY_DEVICE in wanted:
        policies += device_level_policies(level, device_runs_allowed=rules.device_runs_allowed)
    policies += no_model_policies(level, wanted)
    return policies


def matrix_policies(matrix: ClassificationPolicy) -> list[GeneratedPolicy]:
    policies: list[GeneratedPolicy] = []
    for level in DATA_CLASSIFICATION_ORDER:
        policies += level_policies(level, matrix.rules_for(level))
    return policies


# --- Workspace sources ------------------------------------------------------------------------------------------


def _normalized_aliases(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item or "").strip() for item in value if str(item or "").strip()})


def workspace_model_policies(workspace_id: str, model_policy: Mapping[str, Any] | None) -> list[GeneratedPolicy]:
    source = model_policy if isinstance(model_policy, Mapping) else {}
    scope = _workspace(workspace_id)
    prefix = f"workspace:{workspace_id}"
    policies: list[GeneratedPolicy] = []
    denied = _normalized_aliases(source.get("denied_aliases"))
    if denied:
        policies.append(policy(f"{prefix}:model-denied", FORBID, actions=[ACTION_CALL_MODEL],
                               when=[scope, f"{string_set(denied)}.contains(resource.alias)"]))
    allowed = _normalized_aliases(source.get("allowed_aliases"))
    if allowed:
        policies.append(policy(f"{prefix}:model-granted", PERMIT, actions=[ACTION_CALL_MODEL],
                               when=[scope, f"{string_set(allowed)}.contains(resource.alias)"]))
    if source.get("allow_all_admitted_aliases") is True:
        policies.append(policy(f"{prefix}:model-allow-all", PERMIT, actions=[ACTION_CALL_MODEL], when=[scope]))
    return policies


@dataclass(frozen=True, slots=True)
class GatewayTranslation:
    policies: list[GeneratedPolicy] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _command_rule(prefix: str, scope: list[str], rule: Any) -> GeneratedPolicy:
    tokens = " ".join(rule.tokens)
    conditions = [*scope, f"resource.prefixes.contains({literal(tokens)})"]
    if rule.kind == RULE_COMMAND_REQUIRES_ARGUMENT:
        conditions.append(f"!resource.arguments.contains({literal(rule.argument)})")
    elif rule.kind == RULE_COMMAND_ARGUMENT_DENIED:
        conditions.append(f"resource.arguments.contains({literal(rule.argument)})")
    return policy(f"{prefix}:tool-rule:{rule.id}", FORBID, actions=[ACTION_RUN_COMMAND], when=conditions)


def _path_rule(prefix: str, scope: list[str], rule: Any) -> tuple[GeneratedPolicy, bool]:
    pattern = glob_to_like(rule.glob)
    return policy(
        f"{prefix}:tool-rule:{rule.id}", FORBID, actions=PATH_ACTIONS,
        when=[*scope, f"{string_set(sorted(rule.tools))}.contains(context.tool)", f"resource.path like {pattern.text}"],
        annotations=[(APPROXIMATE_ANNOTATION, APPROXIMATE_VALUE)] if pattern.approximate else [],
    ), pattern.approximate


def _client_permission(prefix: str, scope: list[str], index: int, entry: str) -> GeneratedPolicy | None:
    tool, _, rest = entry.partition("(")
    if not rest.endswith(")"):
        return None
    argument = rest[:-1]
    annotations = [("client_permission", entry), (APPROXIMATE_ANNOTATION, APPROXIMATE_VALUE)]
    policy_id = f"{prefix}:client-deny:{index}"
    if tool == "Bash":
        if argument.endswith(":*"):
            tokens = " ".join(argument[:-2].split())
            if not tokens:
                return None
            condition = f"resource.prefixes.contains({literal(tokens)})"
        else:
            condition = f"resource.line == {literal(argument)}"
        return policy(policy_id, FORBID, actions=[ACTION_RUN_COMMAND], when=[*scope, condition],
                      annotations=annotations)
    if tool in _CLIENT_PATH_TOOLS and argument:
        return policy(policy_id, FORBID, actions=PATH_ACTIONS,
                      when=[*scope, f"context.tool == {literal(tool)}",
                            f"resource.path like {glob_to_like(argument).text}"],
                      annotations=annotations)
    return None


def workspace_gateway_policies(workspace_id: str, gateway: GatewayPolicy) -> GatewayTranslation:
    prefix = f"workspace:{workspace_id}"
    gateway_scope = [_workspace(workspace_id), f"context.point == {literal(POINT_GATEWAY)}"]
    translation = GatewayTranslation()
    command_rules = False
    for rule in gateway.tool_rules:
        if rule.kind in (RULE_COMMAND_PREFIX_DENIED, RULE_COMMAND_REQUIRES_ARGUMENT, RULE_COMMAND_ARGUMENT_DENIED):
            command_rules = True
            translation.policies.append(_command_rule(prefix, gateway_scope, rule))
        elif rule.kind == RULE_PATH_DENIED:
            generated, approximate = _path_rule(prefix, gateway_scope, rule)
            translation.policies.append(generated)
            if approximate:
                translation.notes.append(f"tool rule {rule.id}: glob widened to a Cedar like pattern")
    if command_rules:
        translation.policies.append(policy(f"{prefix}:command-unparseable", FORBID, actions=[ACTION_RUN_COMMAND],
                                           when=[*gateway_scope, "!resource.parseable"]))
    client_scope = [_workspace(workspace_id), f"context.point == {literal(POINT_CLIENT)}"]
    for index, entry in enumerate(gateway.deny_permissions, start=1):
        generated = _client_permission(prefix, client_scope, index, entry)
        if generated is None:
            translation.notes.append(f"client deny {index} kept by the client only: {entry}")
        else:
            translation.policies.append(generated)
    for index, entry in enumerate(gateway.ask_permissions, start=1):
        translation.notes.append(f"client ask {index} (a client prompt, not a Cedar decision): {entry}")
    return translation


# --- the whole instance -----------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorkspaceSources:
    workspace_id: str
    gateway: GatewayPolicy | None
    model_policy: Mapping[str, Any] | None
    # Stricter-only classification overrides (``data_policy.overrides``).
    classification_overrides: Mapping[str, Any] | None = None


_OVERRIDE_ACTIONS: dict[str, tuple[str, ...]] = {
    "seat_allowed": (ACTION_USE_SEAT,),
    "requires_governed_routing": (ACTION_USE_SEAT,),
    "reranker_allowed": (ACTION_USE_RERANKER,),
    "remote_embeddings_allowed": (ACTION_USE_REMOTE_EMBEDDINGS,),
    "device_runs_allowed": (ACTION_RUN_ON_DEVICE,),
}


def workspace_classification_policies(workspace_id: str, overrides: Mapping[str, Any] | None) -> list[GeneratedPolicy]:
    if not overrides:
        return []
    prefix = f"workspace:{workspace_id}:classification"
    policies: list[GeneratedPolicy] = []
    for rule, actions in _OVERRIDE_ACTIONS.items():
        if rule in overrides and overrides[rule] == (rule == "requires_governed_routing"):
            policies.append(policy(f"{prefix}:{rule.replace('_', '-')}", FORBID, actions=list(actions),
                                   when=[_workspace(workspace_id)]))
    if overrides.get("log_masking_required") is True:
        policies.append(policy(f"{prefix}:log-masking-not-available", FORBID, actions=TOOL_ACTIONS,
                               when=[_workspace(workspace_id), "context.reads_logs"]))
    connectors = overrides.get("connectors")
    for family, access in sorted(connectors.items()) if isinstance(connectors, Mapping) else []:
        resource = f"resource in {entity(ENTITY_CONNECTOR_FAMILY, family)}"
        if access == ACCESS_NONE:
            policies.append(policy(f"{prefix}:connector:{family}:none", FORBID, actions=CONNECTOR_ACTIONS,
                                   resource=resource, when=[_workspace(workspace_id)]))
        elif access == ACCESS_READ:
            policies.append(policy(f"{prefix}:connector:{family}:read-only", FORBID, actions=[ACTION_WRITE_CONNECTOR],
                                   resource=resource, when=[_workspace(workspace_id)]))
    return policies


def _comment(text: str) -> str:
    # Notes may quote stored values; a comment ends at a newline, so none may survive.
    return "// " + "".join(char if char.isprintable() else " " for char in text)


def instance_baseline(matrix: ClassificationPolicy, workspaces: Sequence[WorkspaceSources]) -> str:
    sections = [
        _comment(f"Octryx baseline policy set - generated, do not edit. Schema {SCHEMA_VERSION}."),
        _comment(f"Classification matrix: {matrix.state}. Workspaces: {len(workspaces)}."),
        "",
        _comment("== platform =="),
        *[item.text + "\n" for item in platform_policies()],
    ]
    for level in DATA_CLASSIFICATION_ORDER:
        generated = level_policies(level, matrix.rules_for(level))
        sections.append(_comment(f"== classification {level} =="))
        sections.extend(item.text + "\n" for item in generated)
    for source in sorted(workspaces, key=lambda item: item.workspace_id):
        sections.append(_comment(f"== workspace {source.workspace_id} =="))
        sections.extend(item.text + "\n" for item in workspace_model_policies(source.workspace_id,
                                                                            source.model_policy))
        sections.extend(item.text + "\n" for item in workspace_device_policies(
            source.workspace_id, source.gateway.raw if source.gateway is not None else None))
        sections.extend(item.text + "\n" for item in workspace_classification_policies(
            source.workspace_id, source.classification_overrides))
        if source.gateway is None:
            sections.append(_comment("agent_gateway_policy is invalid: no gateway rules (the gateway refuses)"))
            continue
        translation = workspace_gateway_policies(source.workspace_id, source.gateway)
        sections.extend(_comment(note) for note in translation.notes)
        sections.extend(item.text + "\n" for item in translation.policies)
    return "\n".join(sections)


__all__ = [
    "CLIENT_TOOL_ACTIONS",
    "FAMILIES",
    "FAMILY_CONTENT",
    "FAMILY_DEVICE",
    "FAMILY_GATEWAY",
    "FAMILY_MODEL",
    "FAMILY_REMOTE",
    "FAMILY_SEAT",
    "FAMILY_TOOL",
    "SECRETS_POLICY_ID",
    "GatewayTranslation",
    "WorkspaceSources",
    "instance_baseline",
    "level_policies",
    "matrix_policies",
    "model_level_policies",
    "platform_policies",
    "remote_level_policies",
    "seat_level_policies",
    "tool_level_policies",
    "workspace_classification_policies",
    "workspace_gateway_policies",
    "workspace_model_policies",
]
