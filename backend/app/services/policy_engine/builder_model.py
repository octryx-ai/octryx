"""The policy builder's structured model: what the guided builder edits.

A model is one custom ``forbid`` policy as catalog blocks (``policy_catalog.json``): who (everyone, users, roles,
groups, except platform admins, session profile/client), which actions, what (connector families, tools, models,
command facts, paths, client tools), where (Workspaces, classification, named connections) and the conditions /
exceptions, and for a content policy (``builder_content``) what the scan must find and the outcome. It
is never stored: ``builder.render`` writes it as Cedar (the stored truth) and ``builder_parse.parse``
reads it back from Cedar.

:func:`model_from_json` is strict: unknown keys, wrong types, unknown values and blocks that do not apply to every
chosen action are issues (``{"path", "code", "message"}``), never silently dropped. Lists keep the given order
without duplicates; actions are kept in catalog order; an unused ``model_mode`` is the default, so equal policies
have equal models.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from . import catalog
from .builder_content import ROUTES, Content, Outcome, check_content, read_content, read_outcome
from .builder_model_reader import ISSUE_INVALID, _paths, _Reader
from .custom_policies import ID_PATTERN
from .schema import RESERVED_ID_PREFIXES

BUILDER_VERSION = "1"
WHO_MODES = ("everyone", "users", "roles", "groups")
MODEL_MODES = ("except", "only")
SESSION_PROFILES = ("governed", "seat")
SEAT_MODES = ("forbidden", "allowed")
MAX_NAME = 120
MAX_DESCRIPTION = 500

ISSUE_NOT_APPLICABLE = "builder_block_not_applicable"
ISSUE_NO_ACTION = "builder_action_required"
ISSUE_WHO_ITEMS = "builder_who_items_required"
ISSUE_PLACEHOLDER = "builder_template_placeholder_missing"
ISSUE_ID = "builder_policy_id_invalid"


@dataclass(frozen=True, slots=True)
class Who:
    mode: str = "everyone"
    items: tuple[str, ...] = ()
    except_admins: bool = False
    session_profile: str = ""
    session_client: str = ""


@dataclass(frozen=True, slots=True)
class What:
    families: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    writes_only: bool = False
    reads_logs: bool = False
    models: tuple[str, ...] = ()
    model_mode: str = "except"
    remote_class_below: str = ""
    programs: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()
    arguments: tuple[str, ...] = ()
    option_values: tuple[str, ...] = ()
    unparseable: bool = False
    paths: tuple[str, ...] = ()
    client_tools: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Where:
    workspaces: tuple[str, ...] = ()
    classification_at_least: str = ""
    classification_is: tuple[str, ...] = ()
    unclassified: bool = False
    connections: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Conditions:
    unless_option_values: tuple[str, ...] = ()
    admission_unverified: bool = False
    seat_mode: str = ""
    governed_required: bool = False
    route: str = ""


@dataclass(frozen=True, slots=True)
class PolicyModel:
    id: str
    name: str = ""
    description: str = ""
    template: str = ""
    actions: tuple[str, ...] = ()
    who: Who = field(default_factory=Who)
    what: What = field(default_factory=What)
    where: Where = field(default_factory=Where)
    conditions: Conditions = field(default_factory=Conditions)
    content: Content = field(default_factory=Content)
    outcome: Outcome = field(default_factory=Outcome)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        return {key: _lists(value) for key, value in data.items()}


def _lists(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _lists(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return list(value)
    return value


# Which catalog block a model field is. ``who.items`` depends on the mode; ``what.models`` on the model mode.
FIELD_BLOCKS: dict[str, str] = {
    "who.except_admins": "who.not_admin", "who.session_profile": "who.session_profile",
    "who.session_client": "who.session_client",
    "where.workspaces": "where.workspace", "where.classification_at_least": "where.classification_at_least",
    "where.classification_is": "where.classification_is", "where.unclassified": "where.unclassified",
    "where.connections": "where.connection",
    "what.families": "what.connector_family", "what.tools": "what.tool", "what.writes_only": "what.writes",
    "what.reads_logs": "what.reads_logs", "what.remote_class_below": "what.remote_class_below",
    "what.programs": "what.program", "what.prefixes": "what.prefix", "what.arguments": "what.has_arguments",
    "what.option_values": "what.option_value", "what.unparseable": "what.unparseable", "what.paths": "what.path_like",
    "what.client_tools": "what.client_tool",
    "conditions.unless_option_values": "cond.option_value_missing",
    "conditions.admission_unverified": "cond.admission_unverified", "conditions.seat_mode": "cond.seat_mode",
    "conditions.governed_required": "cond.governed_required", "conditions.route": "cond.route_is",
    "content.detectors": "content.detected", "content.sticky": "content.conversation_category",
    "content.incomplete": "content.incomplete", "outcome.reroute_to": "outcome.route",
    "outcome.approved_except": "outcome.except_approved",
}
WHO_BLOCKS = {"users": "who.user", "roles": "who.role", "groups": "who.group"}


def used_blocks(model: PolicyModel) -> list[tuple[str, str]]:
    """``(field path, block id)`` of every block the model uses."""
    used: list[tuple[str, str]] = []
    if model.who.mode in WHO_BLOCKS and model.who.items:
        used.append(("who.items", WHO_BLOCKS[model.who.mode]))
    if model.what.models:
        used.append(("what.models", "what.model_not" if model.what.model_mode == "except" else "what.model"))
    for path, block in FIELD_BLOCKS.items():
        section, name = path.split(".")
        if getattr(getattr(model, section), name):
            used.append((path, block))
    return used


def model_from_json(
    raw: Any, custom_detectors: Mapping[str, str] | None = None
) -> tuple[PolicyModel | None, list[dict[str, str]]]:
    """The normalized model, or ``None`` with the issues.

    ``custom_detectors``: the policy set's custom detector ids → categories; a ``custom.*`` detector outside it is
    an issue. ``None`` only when reading back stored Cedar (``builder.parse``), see ``builder_content``.
    """
    reader = _Reader()
    if not isinstance(raw, Mapping):
        return None, [{"path": "", "code": ISSUE_INVALID, "message": "Send the policy model as an object."}]
    top = reader.section(raw, "", PolicyModel)
    policy_id = reader.text(top.get("id"), "id", limit=120)
    if not policy_id or not ID_PATTERN.match(policy_id) or policy_id.startswith(RESERVED_ID_PREFIXES):
        reader.issue("id", ISSUE_ID, "Use letters, digits and ._:/@- (not platform:, classification:, workspace:).")
    actions_raw = reader.items(top.get("actions"), "actions", allowed=catalog.action_ids())
    actions = tuple(action for action in catalog.action_ids() if action in actions_raw)
    who_raw = reader.section(top.get("who"), "who", Who)
    what_raw = reader.section(top.get("what"), "what", What)
    where_raw = reader.section(top.get("where"), "where", Where)
    cond_raw = reader.section(top.get("conditions"), "conditions", Conditions)
    levels = catalog.classification_levels()
    who = _who(reader, who_raw)
    what = _what(reader, what_raw)
    where = _where(reader, where_raw, levels)
    conditions = _conditions(reader, cond_raw)
    outcome = read_outcome(reader, top.get("outcome"))
    content = read_content(reader, top.get("content"), outcome, custom_detectors)
    model = PolicyModel(
        id=policy_id,
        name=reader.text(top.get("name"), "name", limit=MAX_NAME),
        description=reader.text(top.get("description"), "description", limit=MAX_DESCRIPTION),
        template=reader.text(top.get("template"), "template", allowed=[item["id"] for item in catalog.templates()]),
        actions=actions, who=who, what=what, where=where, conditions=conditions, content=content, outcome=outcome,
    )
    _check_semantics(reader, model)
    return (None, reader.issues) if reader.issues else (model, [])


def _who(reader: _Reader, who_raw: Mapping[str, Any]) -> Who:
    who = Who(
        mode=reader.text(who_raw.get("mode"), "who.mode", allowed=WHO_MODES) or "everyone",
        items=reader.items(who_raw.get("items"), "who.items"),
        except_admins=reader.flag(who_raw.get("except_admins"), "who.except_admins"),
        session_profile=reader.text(who_raw.get("session_profile"), "who.session_profile", allowed=SESSION_PROFILES),
        session_client=reader.text(who_raw.get("session_client"), "who.session_client"),
    )
    return who


def _what(reader: _Reader, what_raw: Mapping[str, Any]) -> What:
    what = What(
        families=reader.items(what_raw.get("families"), "what.families", allowed=catalog.connector_families()),
        tools=reader.items(what_raw.get("tools"), "what.tools"),
        writes_only=reader.flag(what_raw.get("writes_only"), "what.writes_only"),
        reads_logs=reader.flag(what_raw.get("reads_logs"), "what.reads_logs"),
        models=reader.items(what_raw.get("models"), "what.models"),
        model_mode=reader.text(what_raw.get("model_mode"), "what.model_mode", allowed=MODEL_MODES) or "except",
        remote_class_below=reader.text(what_raw.get("remote_class_below"), "what.remote_class_below",
                                       allowed=catalog.data_policy_classes()),
        programs=reader.items(what_raw.get("programs"), "what.programs"),
        prefixes=reader.items(what_raw.get("prefixes"), "what.prefixes"),
        arguments=reader.items(what_raw.get("arguments"), "what.arguments"),
        option_values=reader.items(what_raw.get("option_values"), "what.option_values"),
        unparseable=reader.flag(what_raw.get("unparseable"), "what.unparseable"),
        paths=_paths(reader, what_raw.get("paths")),
        client_tools=reader.items(what_raw.get("client_tools"), "what.client_tools", allowed=catalog.client_tools()),
    )
    if not what.models:
        what = replace(what, model_mode="except")
    return what


def _where(reader: _Reader, where_raw: Mapping[str, Any], levels: tuple[str, ...]) -> Where:
    where = Where(
        workspaces=reader.items(where_raw.get("workspaces"), "where.workspaces"),
        classification_at_least=reader.text(where_raw.get("classification_at_least"),
                                            "where.classification_at_least", allowed=levels),
        classification_is=reader.items(where_raw.get("classification_is"), "where.classification_is", allowed=levels),
        unclassified=reader.flag(where_raw.get("unclassified"), "where.unclassified"),
        connections=reader.items(where_raw.get("connections"), "where.connections"),
    )
    return where


def _conditions(reader: _Reader, cond_raw: Mapping[str, Any]) -> Conditions:
    conditions = Conditions(
        unless_option_values=reader.items(cond_raw.get("unless_option_values"), "conditions.unless_option_values"),
        admission_unverified=reader.flag(cond_raw.get("admission_unverified"), "conditions.admission_unverified"),
        seat_mode=reader.text(cond_raw.get("seat_mode"), "conditions.seat_mode", allowed=SEAT_MODES),
        governed_required=reader.flag(cond_raw.get("governed_required"), "conditions.governed_required"),
        route=reader.text(cond_raw.get("route"), "conditions.route", allowed=ROUTES),
    )
    return conditions


def _check_semantics(reader: _Reader, model: PolicyModel) -> None:
    if not model.actions:
        reader.issue("actions", ISSUE_NO_ACTION, "Choose at least one action.")
        return
    if model.who.mode != "everyone" and not model.who.items:
        reader.issue("who.items", ISSUE_WHO_ITEMS, "Pick at least one entry, or choose Everyone.")
    if model.who.mode == "everyone" and model.who.items:
        reader.issue("who.items", ISSUE_INVALID, "Everyone takes no entries.")
    for path, block_id in used_blocks(model):
        block = catalog.block_info(block_id)
        missing = [action for action in model.actions if action not in block["actions"]]
        if missing:
            labels = ", ".join(catalog.action_info(item)["label"] for item in missing)
            reader.issue(path, ISSUE_NOT_APPLICABLE, f"{block['label']} does not apply to {labels}.")
    template = catalog.template_info(model.template) if model.template else None
    check_content(reader, model, {item["field"] for item in (template or {}).get("placeholders", ())})
    for placeholder in (template or {}).get("placeholders", ()):
        section, name = placeholder["field"].split(".")
        if not getattr(getattr(model, section), name):
            reader.issue(placeholder["field"], ISSUE_PLACEHOLDER, f"Fill in: {placeholder['label']}.")


__all__ = [
    "BUILDER_VERSION",
    "Conditions",
    "PolicyModel",
    "What",
    "Where",
    "Who",
    "model_from_json",
    "used_blocks",
]
