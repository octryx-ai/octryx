"""The plain-language sentence of a builder policy, e.g. "Block everyone from changing data
through ServiceNow on connection primary in all Workspaces, except for platform admins."

Segments as in ``policy_sentence`` (verb / value / plain). Ids are shown by name (:class:`entity_listing.NameIndex`);
an id that no longer exists reads "unknown …". One phrase per action group the policy touches, joined with
"and"; the where-part and the exceptions follow. A content policy reads "When a model request contains …"
(``builder_content_sentence``).
"""

from __future__ import annotations

from .builder_content import is_content_policy
from .builder_content_sentence import content_sentence
from .builder_model import PolicyModel
from .catalog import action_info
from .entity_listing import NameIndex, family_label
from .policy_sentence import Segment, connection_label, joined, text, value, verb, workspace_label

TOOL_ACTIONS = ("write_connector", "read_connector", "call_tool")
COMMAND_ACTIONS = ("run_command",)
PATH_ACTIONS = ("read_path", "write_path")
REMOTE_ACTIONS = ("use_remote_embeddings", "use_reranker")


def _who(model: PolicyModel, names: NameIndex) -> list[Segment]:
    who = model.who
    if who.mode == "roles":
        segments = [text("members of role "), value(joined(who.items))]
    elif who.mode == "groups":
        segments = [text("members of group "), value(joined(names.group(item) for item in who.items))]
    elif who.mode == "users":
        segments = [text("user "), value(joined(names.user(item) or f"unknown user {item}" for item in who.items))]
    else:
        segments = [value("everyone")]
    if who.session_profile:
        segments += [text(" in "), value(f"{who.session_profile} sessions")]
    if who.session_client:
        segments += [text(" using "), value(who.session_client)]
    return segments


def _tools(model: PolicyModel, names: NameIndex) -> list[Segment]:
    actions = set(model.actions) & set(TOOL_ACTIONS)
    phrase = ("changing data" if actions == {"write_connector"} else "reading data" if actions == {"read_connector"}
              else "using tools")
    what = model.what
    segments = [value(phrase)]
    if what.families:
        segments += [text(" through "), value(joined(family_label(item) for item in what.families))]
    if what.tools:
        segments += [text(" with "), value(joined(what.tools))]
    if what.reads_logs:
        segments += [text(" when the call "), value("reads logs")]
    if what.writes_only:
        segments += [text(" when the call "), value("changes data")]
    if model.where.connections:
        labels = joined(connection_label(names, item) for item in model.where.connections)
        segments += [text(" on connection "), value(labels)]
    return segments


def _models(model: PolicyModel) -> list[Segment]:
    what = model.what
    if what.models and what.model_mode == "only":
        segments = [text("calling "), value(joined(what.models))]
    else:
        segments = [text("calling "), value("any model" + (f" except {joined(what.models)}" if what.models else ""))]
    if model.conditions.admission_unverified:
        segments += [text(" when the model admission "), value("is not verified")]
    return segments


def _commands(model: PolicyModel) -> list[Segment]:
    what = model.what
    segments: list[Segment] = [text("running ")]
    parts: list[list[Segment]] = []
    if what.programs:
        parts.append([value(joined(what.programs))])
    if what.arguments:
        parts.append([text("with "), value(joined(what.arguments, "and"))])
    if what.prefixes:
        parts.append([text("commands starting with "), value(joined(what.prefixes))])
    if what.option_values:
        parts.append([text("with option "), value(joined(what.option_values))])
    if what.unparseable:
        parts.append([text("commands that "), value("cannot be parsed")])
    if not parts:
        parts.append([value("any shell command")])
    for index, part in enumerate(parts):
        segments += ([text(" ")] if index else []) + part
    if model.conditions.unless_option_values:
        segments += [text(", unless it uses "), value(joined(model.conditions.unless_option_values))]
    return segments


def _paths(model: PolicyModel) -> list[Segment]:
    actions = set(model.actions)
    phrase = ("reading or writing" if set(PATH_ACTIONS) <= actions else "reading" if "read_path" in actions
              else "writing")
    return [text(f"{phrase} files matching "), value(joined(model.what.paths) or "any path")]


def _remote(model: PolicyModel) -> list[Segment]:
    actions = set(model.actions) & set(REMOTE_ACTIONS)
    phrase = ("using remote embeddings or rerankers" if actions == set(REMOTE_ACTIONS)
              else "embedding Knowledge with remote models" if "use_remote_embeddings" in actions
              else "reranking with a remote reranker")
    segments = [value(phrase)]
    if model.what.remote_class_below:
        segments += [text(" whose data-policy class is below "), value(model.what.remote_class_below)]
    return segments


def _seat(model: PolicyModel) -> list[Segment]:
    segments = [value("using a personal seat")]
    if model.conditions.seat_mode:
        segments += [text(" when the seat mode is "), value(model.conditions.seat_mode)]
    if model.conditions.governed_required:
        segments += [text(" when the Workspace "), value("requires governed routing")]
    return segments


def _what(model: PolicyModel, names: NameIndex) -> list[Segment]:
    actions = set(model.actions)
    phrases: list[list[Segment]] = []
    if actions & set(TOOL_ACTIONS):
        phrases.append(_tools(model, names))
    if "call_model" in actions:
        phrases.append(_models(model))
    if actions & set(COMMAND_ACTIONS):
        phrases.append(_commands(model))
    if actions & set(PATH_ACTIONS):
        phrases.append(_paths(model))
    if actions & set(REMOTE_ACTIONS):
        phrases.append(_remote(model))
    if "use_seat" in actions:
        phrases.append(_seat(model))
    segments: list[Segment] = []
    for index, phrase in enumerate(phrases):
        segments += ([text(" and ")] if index else []) + phrase
    if model.what.client_tools:
        segments += [text(" through the client tool "), value(joined(model.what.client_tools))]
    return segments


def _where(model: PolicyModel, names: NameIndex) -> list[Segment]:
    where = model.where
    level = where.classification_at_least
    if where.workspaces:
        segments = [text(" in "), value(joined(workspace_label(names, item) for item in where.workspaces))]
        if level:
            segments += [text(" (classified "), value(f"{level}+"), text(")")]
    elif level:
        segments = [text(" in Workspaces classified "), value(f"{level} or higher")]
    elif where.classification_is:
        segments = [text(" in Workspaces classified "), value(joined(where.classification_is))]
    elif where.unclassified:
        segments = [text(" in Workspaces "), value("without a resolved classification")]
    else:
        segments = [text(" in "), value("all Workspaces")]
    return segments


def sentence(model: PolicyModel, names: NameIndex) -> list[Segment]:
    if is_content_policy(model):
        return content_sentence(model, _who(model, names), _where(model, names))
    coding = [text("coding agents of ")] if set(model.actions) & set(COMMAND_ACTIONS + PATH_ACTIONS) else []
    segments = [verb("Block"), text(" "), *coding, *_who(model, names), text(" from "), *_what(model, names),
                *_where(model, names)]
    if model.who.except_admins:
        segments += [text(", except for "), value("platform admins")]
    segments.append(text("."))
    return segments


def scope(model: PolicyModel, names: NameIndex) -> str:
    where = model.where
    if where.connections:
        return "Connection " + joined(connection_label(names, item) for item in where.connections)
    if len(where.workspaces) == 1:
        return workspace_label(names, where.workspaces[0])
    if where.workspaces:
        return f"{len(where.workspaces)} Workspaces"
    if where.classification_at_least:
        return f"Classification ≥ {where.classification_at_least}"
    if where.classification_is:
        return "Classification = " + ", ".join(where.classification_is)
    if where.unclassified:
        return "Unclassified Workspaces"
    return "All Workspaces"


def action_labels(model: PolicyModel) -> list[str]:
    return [action_info(action)["label"] for action in model.actions]


__all__ = ["action_labels", "scope", "sentence"]
