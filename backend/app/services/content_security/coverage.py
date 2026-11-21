"""What happens to sensitive content where (Content security → Overview): Detect → Decide → Act.

The coverage matrix is computed from what is configured, never typed in:

- **Detect** — the built-in detectors and the published custom detectors (``content_detection``), each mapped to a
  category;
- **Decide** — the shipped defaults of content handling (``handling``: enforced on every model call, every
  driver; a Workspace may choose another action per kind, shown per Workspace by its content-handling endpoint),
  the published custom content policies (Cedar), read through the policy builder model (action, route,
  detectors/categories, outcome), plus the gateway default that secrets never leave;
- **Act** — per surface the strictest outcome: *Refuse*, *Mask → reroute*, *Mask*, *Ask a person*, *Report*, or
  *Not scanned*. A policy outcome only acts while the policy engine enforces; in shadow it is reported.

Surfaces: the user prompt at the company gateway and seat route, a model call of the platform (every driver: the
shipped policies run there), tool results, commands (Command safety), model output (the shipped policies) and
uploads/Knowledge ingest (not scanned).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..content_detection.vocabulary import BUILTIN_DETECTORS, builtin_detector
from ..policy_engine import store
from ..policy_engine.policy_view import builder_model_of, index
from ..policy_engine.runtime import load_mode
from .handling import (
    ACTION_MASK,
    ACTION_REFUSE,
    COMMAND_KINDS,
    POLICY_PROMPT_INJECTION_REFUSED,
    SHIPPED_DEFAULTS,
    SURFACE_PLATFORM,
    KindHandling,
)

OUTCOME_ORDER = {"none": 0, "scanned": 1, "report": 2, "ask": 3, "mask": 4, "reroute": 5, "mask_reroute": 6,
                 "refuse": 7}
OUTCOME_TEXT = {"none": "Not scanned", "scanned": "Scanned, no rule", "report": "Report", "ask": "Ask a person",
                "mask": "Mask", "reroute": "Reroute", "mask_reroute": "Mask → reroute", "refuse": "Refuse"}
OUTCOME_TONE = {"none": "none", "scanned": "report", "report": "report", "ask": "report", "mask": "mask",
                "reroute": "mask", "mask_reroute": "mask", "refuse": "refuse"}
_POLICY_OUTCOME = {"block": "refuse", "mask": "mask", "reroute": "reroute", "mask_reroute": "mask_reroute"}
_PLATFORM_OUTCOME = {ACTION_REFUSE: "refuse", ACTION_MASK: "mask"}
DIRECTION_INPUT = "input"
DIRECTION_OUTPUT = "output"
_SHIPPED_LABELS = {POLICY_PROMPT_INJECTION_REFUSED: "Prompt injection is refused",
                   "platform:credentials-masked": "Credentials are masked",
                   "platform:email-masked": "Email addresses are masked",
                   "platform:internal-ip-reported": "Internal IP addresses are reported"}


def shipped_policies() -> list[dict[str, Any]]:
    """The platform surface's shipped defaults (``handling.SHIPPED_DEFAULTS``) grouped by policy id, with the
    fixed prompt-injection refusal: what a Workspace without its own content handling gets."""
    grouped: dict[str, dict[str, Any]] = {POLICY_PROMPT_INJECTION_REFUSED: {
        "outcome": ACTION_REFUSE, "detectors": {"prompt_injection"}, "directions": [DIRECTION_INPUT]}}
    for kind, action in SHIPPED_DEFAULTS[SURFACE_PLATFORM].items():
        policy_id = KindHandling(kind, action, True).policy_id
        item = grouped.setdefault(policy_id, {"outcome": action, "detectors": set(),
                                              "directions": [DIRECTION_INPUT, DIRECTION_OUTPUT]})
        item["detectors"].add(kind)
    return [{"id": policy_id, "label": _SHIPPED_LABELS.get(policy_id, policy_id),
             "detectors": sorted(item["detectors"]), "outcome": item["outcome"], "directions": item["directions"],
             "commands": bool(item["detectors"] & COMMAND_KINDS),
             "categories": sorted({info.category for info in map(builtin_detector, item["detectors"]) if info})}
            for policy_id, item in grouped.items()]


@dataclass(frozen=True, slots=True)
class Surface:
    key: str
    label: str
    sub: str


SURFACES: tuple[Surface, ...] = (
    Surface("prompt", "User prompt", "company gateway & seats"),
    Surface("chat", "Model call", "platform, every driver"),
    Surface("tool_results", "Tool results", "all tools"),
    Surface("commands", "Commands", "Command safety"),
    Surface("output", "Model output", "responses"),
    Surface("ingest", "Uploads & ingest", "files, Knowledge"),
)


def _strictest(current: str, candidate: str) -> str:
    return candidate if OUTCOME_ORDER[candidate] > OUTCOME_ORDER[current] else current


def _policy_categories(model: Any, custom: Mapping[str, str]) -> set[str]:
    categories = set(model.content.categories)
    for detector in model.content.detectors:
        builtin = builtin_detector(detector)
        category = builtin.category if builtin is not None else custom.get(detector)
        if category:
            categories.add(category)
    return categories


def content_policies(text: str, custom: Mapping[str, str]) -> list[dict[str, Any]]:
    """``[{id, actions, route, categories, outcome}]`` of the builder-made content policies of a published text."""
    found: list[dict[str, Any]] = []
    for statement in index(text):
        model = builder_model_of(statement)
        if model is None or (not model.content.detectors and not model.content.categories):
            continue
        found.append({"id": model.id, "actions": set(model.actions), "route": model.conditions.route,
                      "categories": _policy_categories(model, custom),
                      "outcome": _POLICY_OUTCOME.get(model.outcome.kind, "refuse")})
    return found


def _cell(outcome: str, *, shadow: bool = False, note: str = "") -> dict[str, str]:
    label = OUTCOME_TEXT[outcome] + (f" ({note})" if note else "")
    if shadow and outcome in {"mask", "reroute", "mask_reroute", "refuse"}:
        return {"outcome": outcome, "text": f"{OUTCOME_TEXT[outcome]} (shadow)", "tone": "report"}
    return {"outcome": outcome, "text": label, "tone": OUTCOME_TONE[outcome]}


def _policy_outcome(
    policies: list[dict[str, Any]], detected: set[str], category: str, actions: Iterable[str], routes: set[str]
) -> str:
    outcome = "scanned" if category in detected else "none"
    for item in policies:
        if category in item["categories"] and item["actions"] & set(actions) and item["route"] in routes:
            outcome = _strictest(outcome, item["outcome"])
    return outcome


def _platform_outcome(category: str, direction: str) -> str:
    """The strictest shipped platform default for ``category`` in ``direction`` (prompt injection: input only)."""
    outcome = "none"
    for policy in shipped_policies():
        if direction in policy["directions"] and category in policy["categories"]:
            outcome = _strictest(outcome, _PLATFORM_OUTCOME.get(policy["outcome"], "report"))
    return outcome


@dataclass(frozen=True, slots=True)
class _CoverageInputs:
    policies: list[dict[str, Any]]
    detected: set[str]
    shadow: bool
    chain: set[str]


def _surface_cell(surface_key: str, key: str, inputs: _CoverageInputs) -> dict[str, str]:
    shadow = inputs.shadow
    if surface_key == "prompt":
        outcome = _policy_outcome(inputs.policies, inputs.detected, key, ["call_model"], {"", "seat", "governed"})
        return _cell("refuse") if key == "secrets" else _cell(outcome, shadow=shadow)
    if surface_key == "chat":
        policy = _policy_outcome(inputs.policies, inputs.detected, key, ["call_model"], {"", "governed"})
        platform = _platform_outcome(key, DIRECTION_INPUT)
        if platform != "none" and OUTCOME_ORDER[platform] >= OUTCOME_ORDER[policy]:
            return _cell(platform, note="platform")
        return _cell(policy, shadow=shadow)
    if surface_key == "tool_results":
        outcome = _policy_outcome(
            inputs.policies, inputs.detected, key, ["receive_tool_result"], {"", "seat", "governed"}
        )
        return _cell(outcome, shadow=shadow)
    if surface_key == "commands":
        outcome = "none"
        if key == "secrets" and "secret_access" in inputs.chain:
            outcome = "ask"
        command_categories = {info.category for info in map(builtin_detector, COMMAND_KINDS) if info}
        if "command_guardrail" in inputs.chain and key in command_categories:
            outcome = _strictest(outcome, "ask")
        return _cell(outcome)
    if surface_key == "output":
        outcome = _platform_outcome(key, DIRECTION_OUTPUT)
        return _cell(outcome, note="platform") if outcome != "none" else _cell("none")
    return _cell("none")


async def coverage(db: AsyncSession) -> dict[str, Any]:
    from app.services.command_safety.reading import platform_settings

    published = await store.published(db)
    definitions = store.detector_definitions(published)
    custom = {item.id: item.category for item in definitions.detectors}
    categories = [{"id": item.id, "label": item.label} for item in definitions.all_categories()
                  if any(det.category == item.id for det in BUILTIN_DETECTORS) or item.id in custom.values()]
    policies = content_policies(str(published.policies_text or "") if published else "", custom)
    shadow = await load_mode(db) != "enforce"
    detected = {det.category for det in BUILTIN_DETECTORS} | set(custom.values())
    gate = await platform_settings(db)
    chain = {item["key"] for item in gate["checks"] if item["enabled"]}
    inputs = _CoverageInputs(policies=policies, detected=detected, shadow=shadow, chain=chain)

    rows = []
    for surface in SURFACES:
        cells = []
        for category in categories:
            key = category["id"]
            cells.append({"category": key, **_surface_cell(surface.key, key, inputs)})
        rows.append({"key": surface.key, "label": surface.label, "sub": surface.sub, "cells": cells})
    return {
        "categories": categories,
        "rows": rows,
        "mode": "shadow" if shadow else "enforce",
        "detectors": len(BUILTIN_DETECTORS) + len(definitions.detectors),
        "custom_detectors": len(definitions.detectors),
        "content_policies": len(policies),
        "published_version": published.version if published else None,
        "platform_policies": shipped_policies(),
    }


__all__ = ["SURFACES", "content_policies", "coverage"]
