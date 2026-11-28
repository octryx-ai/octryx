"""The plain-language sentence of a builder content policy."""

from __future__ import annotations

from collections.abc import Sequence

from ..content_detection.vocabulary import BUILTIN_CATEGORIES, CUSTOM_PREFIX
from .builder_content import routes
from .policy_sentence import Segment, joined, text, value, verb
from .schema import ACTION_CALL_MODEL

# How a sentence names what a built-in detector finds (plural nouns).
DETECTOR_NOUNS = {
    "iban": "IBANs", "email": "email addresses", "phone": "phone numbers", "secrets": "credentials",
}
CATEGORY_LABELS = {item.id: item.label.lower() for item in BUILTIN_CATEGORIES}


def detector_noun(detector: str) -> str:
    if detector in DETECTOR_NOUNS:
        return DETECTOR_NOUNS[detector]
    return detector.removeprefix(CUSTOM_PREFIX).replace("_", " ")


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category.replace("_", " "))


def _verb(kind: str, alias: str) -> list[Segment]:
    if kind == "mask":
        return [verb("mask"), text(" them")]
    if kind == "reroute":
        return [verb("route"), text(" it to "), value(alias)]
    if kind == "mask_reroute":
        return [verb("mask"), text(" them and "), verb("route"), text(" the request to "), value(alias)]
    return [verb("block"), text(" it")]


def content_sentence(model, who: Sequence[Segment], where: Sequence[Segment]) -> list[Segment]:
    content, outcome = model.content, model.outcome
    alias = outcome.reroute_to or "‹approved model›"
    request = "model request" if model.actions == (ACTION_CALL_MODEL,) else "tool result"
    segments: list[Segment] = [text("When a "), value(request)]
    if model.conditions.route:
        segments += [text(" on the "), value(f"{model.conditions.route} route")]
    segments += [text(" contains "), value(joined(detector_noun(item) for item in content.detectors))]
    if content.incomplete:
        segments.append(text(" (or could not be fully scanned)"))
    segments += [text(", "), *_verb(outcome.kind, alias), text(", for "), *who, *where]
    if model.who.except_admins:
        segments += [text(", except for "), value("platform admins")]
    if outcome.approved_except:
        segments += [text(", except on models approved for "),
                     value(joined((category_label(item) for item in content.categories), "and"))]
    segments.append(text("."))
    if routes(outcome) and content.sticky:
        segments += [text(" The conversation stays on "), value(alias), text(" until it is cleared.")]
    if routes(outcome):
        segments += [text(" If "), value(alias), text(" cannot take the request, it is "), verb("blocked"), text(".")]
    return segments


__all__ = ["DETECTOR_NOUNS", "category_label", "content_sentence", "detector_noun"]
