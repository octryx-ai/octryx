"""Content policies in the guided builder: what the scan must find, and what happens then."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..content_detection.vocabulary import CUSTOM_PREFIX, MASK_STYLES, MASK_TYPE_TOKEN, builtin_detector
from .cedar_text import literal, string_set
from .schema import ACTION_CALL_MODEL, ACTION_RECEIVE_TOOL_RESULT

CONTENT_ACTIONS = (ACTION_CALL_MODEL, ACTION_RECEIVE_TOOL_RESULT)
OUTCOMES = ("block", "mask", "reroute", "mask_reroute")
ROUTE_OUTCOMES = frozenset({"reroute", "mask_reroute"})
MASK_OUTCOMES = frozenset({"mask", "mask_reroute"})
ROUTES = ("seat", "governed")
ANNOTATIONS = frozenset({"obligation", "reroute_to", "mask", "mask_style"})

ISSUE_CONTENT_ACTION = "builder_content_action_invalid"
ISSUE_DETECTOR_UNKNOWN = "builder_detector_unknown"
ISSUE_DETECTORS_REQUIRED = "builder_content_detectors_required"
ISSUE_OUTCOME = "builder_outcome_invalid"
ISSUE_ROUTE_TARGET = "builder_reroute_target_required"
ISSUE_CATEGORIES = "builder_content_categories_invalid"
ISSUE_NOT_APPLICABLE = "builder_block_not_applicable"

INCOMPLETE = "(context.content.scanned && !context.content.complete)"


@dataclass(frozen=True, slots=True)
class Content:
    detectors: tuple[str, ...] = ()
    sticky: bool = False
    incomplete: bool = False
    categories: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Outcome:
    kind: str = "block"
    reroute_to: str = ""
    mask_style: str = ""
    approved_except: bool = False


def routes(outcome: Outcome) -> bool:
    return outcome.kind in ROUTE_OUTCOMES


def masks(outcome: Outcome) -> bool:
    return outcome.kind in MASK_OUTCOMES


def is_content_policy(model: Any) -> bool:
    return model.content != Content() or model.outcome != Outcome()


def custom_categories(definitions: Any) -> dict[str, str]:
    return {item.id: item.category for item in definitions.detectors}


def _categories_needed(outcome: Outcome) -> bool:
    return routes(outcome) or outcome.approved_except


# --- reading ----------------------------------------------------------------------------------------------------


def read_outcome(reader: Any, raw: Any) -> Outcome:
    section = reader.section(raw, "outcome", Outcome)
    kind = reader.text(section.get("kind"), "outcome.kind", allowed=OUTCOMES) or "block"
    reroute_to = reader.text(section.get("reroute_to"), "outcome.reroute_to")
    style = reader.text(section.get("mask_style"), "outcome.mask_style", allowed=MASK_STYLES)
    approved_except = reader.flag(section.get("approved_except"), "outcome.approved_except")
    # Unused fields are the default, so equal policies have equal models (like ``what.model_mode``).
    return Outcome(kind=kind, reroute_to=reroute_to if kind in ROUTE_OUTCOMES else "",
                   mask_style=(style or MASK_TYPE_TOKEN) if kind in MASK_OUTCOMES else "",
                   approved_except=approved_except)


def read_content(reader: Any, raw: Any, outcome: Outcome, custom: Mapping[str, str] | None) -> Content:
    section = reader.section(raw, "content", Content)
    detectors = reader.items(section.get("detectors"), "content.detectors")
    given = reader.items(section.get("categories"), "content.categories")
    known: list[str] = []
    unresolved = False
    for index, detector in enumerate(detectors):
        info = builtin_detector(detector)
        if info is not None:
            known.append(info.category)
        elif custom is not None and detector in custom:
            known.append(custom[detector])
        elif custom is None and detector.startswith(CUSTOM_PREFIX) and len(detector) > len(CUSTOM_PREFIX):
            unresolved = True
        else:
            reader.issue(f"content.detectors[{index}]", ISSUE_DETECTOR_UNKNOWN,
                         f"Unknown detector {detector}: use a built-in detector or a custom detector of this "
                         "policy set (Detectors tab).")
    derived = tuple(dict.fromkeys(known))
    categories: tuple[str, ...] = ()
    if _categories_needed(outcome):
        if unresolved:
            categories = given
            if not given or not set(derived) <= set(given):
                reader.issue("content.categories", ISSUE_CATEGORIES, "The categories follow the detectors.")
        else:
            categories = derived
            if given and given != derived:
                reader.issue("content.categories", ISSUE_CATEGORIES, "The categories follow the detectors.")
    return Content(detectors=detectors, sticky=reader.flag(section.get("sticky"), "content.sticky"),
                   incomplete=reader.flag(section.get("incomplete"), "content.incomplete"), categories=categories)


def check_content(reader: Any, model: Any, placeholders: set[str]) -> None:
    if not is_content_policy(model):
        return
    content, outcome = model.content, model.outcome
    if len(model.actions) != 1 or model.actions[0] not in CONTENT_ACTIONS:
        reader.issue("actions", ISSUE_CONTENT_ACTION, "A content condition applies to exactly one action: Call a "
                     "model or Receive a tool result.")
        return
    action = model.actions[0]
    if not content.detectors and "content.detectors" not in placeholders:
        reader.issue("content.detectors", ISSUE_DETECTORS_REQUIRED, "Pick at least one detector.")
    if action == ACTION_RECEIVE_TOOL_RESULT and routes(outcome):
        reader.issue("outcome.kind", ISSUE_OUTCOME, "Tool results are masked or blocked at the source; routing "
                     "applies to model requests.")
    if content.sticky and not routes(outcome):
        reader.issue("content.sticky", ISSUE_OUTCOME, "\"The conversation already contained this category\" "
                     "needs a route outcome (Route to an approved model, or Mask and route).")
    if outcome.approved_except and not (outcome.kind == "mask" and action == ACTION_CALL_MODEL):
        reader.issue("outcome.approved_except", ISSUE_OUTCOME, "The approved-model exception is for Mask on Call "
                     "a model.")
    if routes(outcome) and not outcome.reroute_to and "outcome.reroute_to" not in placeholders:
        reader.issue("outcome.reroute_to", ISSUE_ROUTE_TARGET, "Pick the approved model to route to.")
    if model.what.models or model.conditions.admission_unverified:
        reader.issue("what.models" if model.what.models else "conditions.admission_unverified", ISSUE_NOT_APPLICABLE,
                     "Model conditions do not combine with a content condition; use the outcome's approved-model "
                     "exception instead.")


# --- rendering --------------------------------------------------------------------------------------------------


def content_when(model: Any, others: int) -> list[str]:
    parts: list[str] = []
    if model.conditions.route:
        parts.append(f"context.route == {literal(model.conditions.route)}")
    content = model.content
    if not content.detectors:
        return parts
    group = [f"context.content.detected.containsAny({string_set(content.detectors)})"]
    if content.incomplete:
        group.append(INCOMPLETE)
    if content.sticky and routes(model.outcome):
        sensitive = f"principal.sensitive.containsAny({string_set(content.categories)})"
        group.append(f"(principal is AgentSession && {sensitive})")
    joined = " || ".join(group)
    parts.append(f"({joined})" if len(group) > 1 and (others or parts) else joined)
    return parts


def content_unless(model: Any) -> list[str]:
    content, outcome = model.content, model.outcome
    if not content.detectors:
        return []
    categories = string_set(content.categories)
    if routes(outcome):
        governed = f'context.route == "governed" && resource.approved_for.containsAll({categories})'
        if masks(outcome):
            governed += f" && !context.content.detected.containsAny({string_set(content.detectors)})"
        return [governed]
    if outcome.approved_except:
        return [f"resource.approved_for.containsAll({categories})"]
    return []


def content_annotations(model: Any) -> list[tuple[str, str]]:
    outcome = model.outcome
    if not model.content.detectors or outcome.kind == "block":
        return []
    annotations = [("obligation", outcome.kind)]
    if routes(outcome):
        annotations.append(("reroute_to", outcome.reroute_to))
    if masks(outcome):
        annotations += [("mask", ",".join(model.content.detectors)), ("mask_style", outcome.mask_style)]
    return annotations


__all__ = [
    "ANNOTATIONS",
    "CONTENT_ACTIONS",
    "Content",
    "OUTCOMES",
    "Outcome",
    "ROUTES",
    "check_content",
    "content_annotations",
    "content_unless",
    "content_when",
    "custom_categories",
    "is_content_policy",
    "masks",
    "read_content",
    "read_outcome",
    "routes",
]
