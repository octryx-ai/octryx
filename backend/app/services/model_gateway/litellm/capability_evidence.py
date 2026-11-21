"""Probe evidence for LiteLLM gateway model groups.

A capability is advertised (and permitted) only when the catalog probe proved
it. A gateway catalog that carries no capability information proves nothing:
the capability stays unknown and a request that needs it is refused rather than
attempted optimistically.

Evidence is cached per endpoint for a bounded TTL so a tool-enabled turn does
not pay a probe round trip every time. The cache is explicit, inspectable, and
resettable — it is a capability-evidence cache, never a fallback.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .alias_catalog import (
    CAPABILITY_REASONING,
    CAPABILITY_STRUCTURED_OUTPUT,
    CAPABILITY_TOOLS,
    CAPABILITY_VISION,
)

# LiteLLM reports model capabilities under ``model_info``. Only these exact
# fields count as evidence; an absent field proves nothing.
CAPABILITY_EVIDENCE_FIELDS: dict[str, str] = {
    CAPABILITY_TOOLS: "supports_function_calling",
    CAPABILITY_VISION: "supports_vision",
    CAPABILITY_STRUCTURED_OUTPUT: "supports_response_schema",
    CAPABILITY_REASONING: "supports_reasoning",
}

DEFAULT_EVIDENCE_TTL_SECONDS = 300.0


@dataclass(frozen=True, slots=True)
class ModelGroupEvidence:
    model_group: str
    proven_capabilities: frozenset[str]
    refuted_capabilities: frozenset[str]
    max_input_tokens: int | None


@dataclass(frozen=True, slots=True)
class ProbeEvidence:
    observed_at: float
    model_groups: Mapping[str, ModelGroupEvidence]

    def for_model_group(self, model_group: str) -> ModelGroupEvidence | None:
        return self.model_groups.get(model_group)


def _model_group_evidence(entry: Mapping[str, Any], *, model_group_field: str) -> ModelGroupEvidence | None:
    model_group = str(entry.get(model_group_field) or "").strip()
    if not model_group:
        return None
    info = entry.get("model_info")
    info = info if isinstance(info, Mapping) else {}
    proven: set[str] = set()
    refuted: set[str] = set()
    for capability, field_name in CAPABILITY_EVIDENCE_FIELDS.items():
        value = info.get(field_name)
        if value is True:
            proven.add(capability)
        elif value is False:
            refuted.add(capability)
    raw_max_input = info.get("max_input_tokens")
    max_input_tokens = (
        int(raw_max_input)
        if isinstance(raw_max_input, int) and not isinstance(raw_max_input, bool) and raw_max_input > 0
        else None
    )
    return ModelGroupEvidence(model_group, frozenset(proven), frozenset(refuted), max_input_tokens)


def parse_probe_evidence(payload: Any, *, model_group_field: str, observed_at: float) -> ProbeEvidence | None:
    """Parse a pinned ``openai_model_list`` catalog payload into probe evidence."""

    if not isinstance(payload, Mapping):
        return None
    entries = payload.get("data")
    if not isinstance(entries, list):
        return None
    model_groups: dict[str, ModelGroupEvidence] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        evidence = _model_group_evidence(entry, model_group_field=model_group_field)
        if evidence is not None:
            model_groups[evidence.model_group] = evidence
    return ProbeEvidence(observed_at=observed_at, model_groups=model_groups)


class ProbeEvidenceCache:
    """Bounded per-endpoint cache of catalog probe evidence."""

    def __init__(self, *, ttl_seconds: float = DEFAULT_EVIDENCE_TTL_SECONDS, clock=time.monotonic):
        self._ttl_seconds = max(0.0, float(ttl_seconds))
        self._clock = clock
        self._entries: dict[tuple[str, str], ProbeEvidence] = {}

    def now(self) -> float:
        return float(self._clock())

    def get(self, base_url: str, models_path: str) -> ProbeEvidence | None:
        evidence = self._entries.get((base_url, models_path))
        if evidence is None:
            return None
        if self.now() - evidence.observed_at > self._ttl_seconds:
            self._entries.pop((base_url, models_path), None)
            return None
        return evidence

    def store(self, base_url: str, models_path: str, evidence: ProbeEvidence) -> None:
        self._entries[(base_url, models_path)] = evidence

    def reset(self) -> None:
        self._entries.clear()


PROBE_EVIDENCE_CACHE = ProbeEvidenceCache()


__all__ = [
    "CAPABILITY_EVIDENCE_FIELDS",
    "DEFAULT_EVIDENCE_TTL_SECONDS",
    "PROBE_EVIDENCE_CACHE",
    "ModelGroupEvidence",
    "ProbeEvidence",
    "ProbeEvidenceCache",
    "parse_probe_evidence",
]
