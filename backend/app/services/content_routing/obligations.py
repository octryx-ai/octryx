"""Obligations of content policies: repair a request instead of refusing it, never widen access."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache

from ..content_detection.vocabulary import BUILTIN_DETECTOR_IDS, CUSTOM_PREFIX, MASK_STYLES
from ..policy_engine.policy_text import index_statements, split_statements
from ..policy_engine.runtime import current_runtime

logger = logging.getLogger(__name__)

OBLIGATION_MASK = "mask"
OBLIGATION_REROUTE = "reroute"
OBLIGATION_MASK_REROUTE = "mask_reroute"
OBLIGATIONS: tuple[str, ...] = (OBLIGATION_MASK, OBLIGATION_REROUTE, OBLIGATION_MASK_REROUTE)
ANNOTATION_OBLIGATION = "obligation"
ANNOTATION_MASK = "mask"
ANNOTATION_MASK_STYLE = "mask_style"
ANNOTATION_REROUTE_TO = "reroute_to"

REASON_CONFLICT = "content_obligation_conflict"
REASON_INSUFFICIENT = "content_obligation_insufficient"
REASON_ROUTE_UNAVAILABLE = "content_route_unavailable"
OUTCOME_REMEDIED = "remedied"
OUTCOME_WOULD_REMEDY = "would_remedy"


@dataclass(frozen=True, slots=True)
class Obligation:
    kind: str
    policies: tuple[str, ...]
    mask: frozenset[str] = frozenset()
    mask_style: str | None = None
    reroute_to: str = ""

    @property
    def masks(self) -> bool:
        return self.kind in (OBLIGATION_MASK, OBLIGATION_MASK_REROUTE) and bool(self.mask)

    @property
    def reroutes(self) -> bool:
        return self.kind in (OBLIGATION_REROUTE, OBLIGATION_MASK_REROUTE)


@dataclass(frozen=True, slots=True)
class Unresolved:
    reason: str
    policies: tuple[str, ...]


@lru_cache(maxsize=16)
def policy_annotations(custom_text: str) -> Mapping[str, Mapping[str, str]]:
    if not custom_text or not split_statements(custom_text).statements:
        return {}
    return {item.policy_id: dict(item.annotations) for item in index_statements(custom_text)}


def _items(value: str) -> frozenset[str]:
    return frozenset(item.strip() for item in value.split(",") if item.strip())


def resolve(determining: Iterable[str], custom_ids: frozenset[str], custom_text: str, *,
            tool_result: bool = False, plain_reason: str = "content_policy_denied") -> Obligation | Unresolved:
    policies = tuple(determining)
    if not policies or any(policy_id not in custom_ids for policy_id in policies):
        return Unresolved(plain_reason, policies)
    annotations = policy_annotations(custom_text)

    def repairs(policy_id: str) -> bool:
        kind = annotations.get(policy_id, {}).get(ANNOTATION_OBLIGATION, "")
        return kind in OBLIGATIONS and (not tool_result or kind == OBLIGATION_MASK)

    blocking = tuple(policy_id for policy_id in policies if not repairs(policy_id))
    if blocking:  # a plain block wins
        return Unresolved(plain_reason, blocking)
    masks: set[str] = set()
    styles: list[str] = []
    targets: set[str] = set()
    for policy_id in policies:
        found = annotations[policy_id]
        kind = found[ANNOTATION_OBLIGATION]
        if kind in (OBLIGATION_MASK, OBLIGATION_MASK_REROUTE):
            masks |= _items(found.get(ANNOTATION_MASK, ""))
            style = found.get(ANNOTATION_MASK_STYLE, "")
            if style in MASK_STYLES:
                styles.append(style)
        if kind in (OBLIGATION_REROUTE, OBLIGATION_MASK_REROUTE):
            targets.add(found.get(ANNOTATION_REROUTE_TO, "").strip())
    if len(targets) > 1 or "" in targets:
        return Unresolved(REASON_CONFLICT, policies)
    unknown = sorted(item for item in masks if item not in BUILTIN_DETECTOR_IDS and not item.startswith(CUSTOM_PREFIX))
    if unknown:  # a detector a stored policy names and the platform no longer has: ignored, never an error
        logger.info("content_obligation_unknown_detector detectors=%s policies=%s", ",".join(unknown),
                    ",".join(policies))
        masks -= set(unknown)
    if targets:
        kind = OBLIGATION_MASK_REROUTE if masks else OBLIGATION_REROUTE
    else:
        kind = OBLIGATION_MASK
    # One style for the request: the first deciding policy's (deterministic order of the determining list).
    return Obligation(kind, policies, frozenset(masks), styles[0] if styles else None, next(iter(targets), ""))


# Every surface resolves a denial against the Workspace's published set as it is loaded now.
def workspace_obligation(determining: Iterable[str], *, tool_result: bool = False) -> Obligation | Unresolved:
    runtime = current_runtime()
    return resolve(determining, runtime.custom_ids, runtime.custom_text, tool_result=tool_result)


__all__ = [
    "ANNOTATION_MASK",
    "ANNOTATION_MASK_STYLE",
    "ANNOTATION_OBLIGATION",
    "ANNOTATION_REROUTE_TO",
    "OBLIGATIONS",
    "OBLIGATION_MASK",
    "OBLIGATION_MASK_REROUTE",
    "OBLIGATION_REROUTE",
    "OUTCOME_REMEDIED",
    "OUTCOME_WOULD_REMEDY",
    "REASON_CONFLICT",
    "REASON_INSUFFICIENT",
    "REASON_ROUTE_UNAVAILABLE",
    "Obligation",
    "Unresolved",
    "policy_annotations",
    "resolve",
    "workspace_obligation",
]
