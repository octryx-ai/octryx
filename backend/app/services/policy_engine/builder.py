"""Builder model ↔ Cedar, deterministic both ways."""

from __future__ import annotations

from collections.abc import Callable

from ..model_gateway.data_policy.classification import classification_rank
from .builder_content import content_annotations, content_unless, content_when
from .builder_model import BUILDER_VERSION, PolicyModel
from .cedar_text import entity, literal, policy, string_set

ENTITY_OF_MODE = {"users": "User", "roles": "Role", "groups": "Group"}


def _rank(level: str) -> int:
    rank = classification_rank(level)
    if rank is None:
        raise KeyError(level)
    return rank


def _class_rank(value: str) -> int:
    return _rank(value)


def _any(values: tuple[str, ...], render_one: Callable[[str], str]) -> str:
    parts = [render_one(value) for value in values]
    return parts[0] if len(parts) == 1 else "(" + " || ".join(parts) + ")"


def _when(model: PolicyModel) -> list[str]:
    who, what, where, cond = model.who, model.what, model.where, model.conditions
    kind = ENTITY_OF_MODE.get(who.mode)
    conditions: list[str] = []
    if kind and len(who.items) > 1:
        conditions.append(_any(who.items, lambda item: f"principal in {entity(kind, item)}"))
    if who.session_profile:
        conditions.append(f"principal is AgentSession && principal.profile == {literal(who.session_profile)}")
    if who.session_client:
        conditions.append(f"principal is AgentSession && principal.client == {literal(who.session_client)}")
    if where.workspaces:
        workspaces = ", ".join(entity("Workspace", item) for item in where.workspaces)
        conditions.append(f"context.workspace in [{workspaces}]")
    if where.classification_is:
        conditions.append("context.workspace has classification && "
                          f"{string_set(where.classification_is)}.contains(context.workspace.classification)")
    if where.classification_at_least:
        conditions.append("context.workspace has classification_rank && "
                          f"context.workspace.classification_rank >= {_rank(where.classification_at_least)}")
    if where.unclassified:
        conditions.append("!(context.workspace has classification)")
    if what.families:
        conditions.append("resource in [" + ", ".join(entity("ConnectorFamily", item) for item in what.families) + "]")
    if what.tools:
        conditions.append("resource in [" + ", ".join(entity("Tool", item) for item in what.tools) + "]")
    if where.connections:
        conditions.append(f"context.connections.containsAny({string_set(where.connections)})")
    if what.writes_only:
        conditions.append("context.writes")
    if what.reads_logs:
        conditions.append("context.reads_logs")
    if what.models and what.model_mode == "only":
        conditions.append(f"{string_set(what.models)}.contains(resource.alias)")
    if what.remote_class_below:
        rank = _class_rank(what.remote_class_below)
        conditions.append(f"resource has data_policy_rank && resource.data_policy_rank < {rank}")
    if what.programs:
        conditions.append(f"{string_set(what.programs)}.contains(resource.program)")
    if what.prefixes:
        conditions.append(f"resource.prefixes.containsAny({string_set(what.prefixes)})")
    if what.arguments:
        conditions.append(f"resource.arguments.containsAll({string_set(what.arguments)})")
    if what.option_values:
        conditions.append(f"resource.argument_values.containsAny({string_set(what.option_values)})")
    if what.unparseable:
        conditions.append("!resource.parseable")
    if what.paths:
        conditions.append(_any(what.paths, lambda item: f"resource.path like {literal(item)}"))
    if what.client_tools:
        conditions.append(f"{string_set(what.client_tools)}.contains(context.tool)")
    if cond.admission_unverified:
        conditions.append("!context.admission_verified")
    if cond.seat_mode:
        conditions.append(f"resource.seat_mode == {literal(cond.seat_mode)}")
    if cond.governed_required:
        conditions.append("resource.requires_governed_routing")
    return conditions


def _unless(model: PolicyModel) -> list[str]:
    exceptions: list[str] = content_unless(model)
    if model.what.models and model.what.model_mode == "except":
        exceptions.append(f"{string_set(model.what.models)}.contains(resource.alias)")
    if model.conditions.unless_option_values:
        exceptions.append(f"resource.argument_values.containsAny({string_set(model.conditions.unless_option_values)})")
    if model.who.except_admins:
        exceptions.append("(principal is User && principal.platform_admin)")
    return exceptions


def render(model: PolicyModel) -> str:
    kind = ENTITY_OF_MODE.get(model.who.mode)
    single = kind and len(model.who.items) == 1
    principal = f"principal in {entity(kind, model.who.items[0])}" if single else "principal"
    annotations = [(name, value) for name, value in (("name", model.name), ("description", model.description),
                                                     ("template", model.template)) if value]
    annotations.append(("builder", BUILDER_VERSION))
    annotations += content_annotations(model)
    exceptions = _unless(model)
    conditions = _when(model)
    conditions += content_when(model, len(conditions))
    return policy(model.id, "forbid", actions=model.actions, principal=principal, when=conditions,
                  unless=[" || ".join(exceptions)] if exceptions else [], annotations=annotations).text


__all__ = ["ENTITY_OF_MODE", "render"]
