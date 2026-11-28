"""Pure rules of a Model Policy: entry shape, digest, and alias admission."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ..model_gateway.litellm.alias_catalog import (
    ALIAS_DENIAL_CATALOG_MISSING,
    GATEWAY_CAPABILITIES,
    resolve_alias_admission,
)
from .digest import content_digest
from .errors import MODEL_POLICY_ENTRIES_INVALID, RegistryRefusalError

MAX_ENTRIES = 16
ALIAS_MAX_LENGTH = 200
REASON_NO_GATEWAY_PROVIDER = "no_gateway_provider"
REASON_CAPABILITY_MISSING = "alias_capability_missing"


def _refuse(reason: str, index: int | None = None) -> RegistryRefusalError:
    facts: dict[str, Any] = {"reason": reason}
    if index is not None:
        facts["entry_index"] = index
    return RegistryRefusalError(MODEL_POLICY_ENTRIES_INVALID, **facts)


def normalize_entries(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise _refuse("entries_empty")
    if len(raw) > MAX_ENTRIES:
        raise _refuse("too_many_entries")
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or set(item) - {"alias", "required_capabilities"}:
            raise _refuse("entry_malformed", index)
        alias = item.get("alias")
        if not isinstance(alias, str) or not alias.strip() or len(alias) > ALIAS_MAX_LENGTH:
            raise _refuse("alias_invalid", index)
        alias = alias.strip()
        if alias in seen:
            raise _refuse("alias_duplicate", index)
        seen.add(alias)
        capabilities = item.get("required_capabilities", [])
        if not isinstance(capabilities, list) or any(
            not isinstance(value, str) or value not in GATEWAY_CAPABILITIES for value in capabilities
        ):
            raise _refuse("capability_unknown", index)
        entries.append({"alias": alias, "required_capabilities": sorted(set(capabilities))})
    return entries


def entries_digest(entries: list[dict[str, Any]]) -> str:
    return content_digest({"kind": "ModelPolicy", "entries": entries})


@dataclass(frozen=True, slots=True)
class AliasAdmissionState:
    alias: str
    status: str  # "admitted" | "needs_configuration"
    reason: str | None = None
    missing_capabilities: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "status": self.status,
            "reason": self.reason,
            "missing_capabilities": list(self.missing_capabilities),
        }


@dataclass(frozen=True, slots=True)
class ModelPolicyAdmission:
    entries: tuple[AliasAdmissionState, ...]

    @property
    def status(self) -> str:
        return "admitted" if all(entry.status == "admitted" for entry in self.entries) else "needs_configuration"

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "entries": [entry.as_dict() for entry in self.entries]}


def _admit_one(entry: dict[str, Any], gateway_configs: list[Any]) -> AliasAdmissionState:
    alias = entry["alias"]
    if not gateway_configs:
        return AliasAdmissionState(alias, "needs_configuration", REASON_NO_GATEWAY_PROVIDER)
    reason = ALIAS_DENIAL_CATALOG_MISSING
    missing_best: tuple[str, ...] | None = None
    for config_json in gateway_configs:
        admission = resolve_alias_admission(alias, config_json)
        if admission.entry is None:
            reason = admission.denial_reason
            continue
        missing = tuple(sorted(set(entry["required_capabilities"]) - set(admission.entry.requested_capabilities)))
        if not missing:
            return AliasAdmissionState(alias, "admitted")
        missing_best = missing if missing_best is None or len(missing) < len(missing_best) else missing_best
    if missing_best is not None:
        return AliasAdmissionState(alias, "needs_configuration", REASON_CAPABILITY_MISSING, missing_best)
    return AliasAdmissionState(alias, "needs_configuration", reason)


def evaluate_admission(entries: Iterable[dict[str, Any]], gateway_configs: list[Any]) -> ModelPolicyAdmission:
    return ModelPolicyAdmission(tuple(_admit_one(entry, gateway_configs) for entry in entries))


__all__ = [
    "MAX_ENTRIES",
    "REASON_CAPABILITY_MISSING",
    "REASON_NO_GATEWAY_PROVIDER",
    "AliasAdmissionState",
    "ModelPolicyAdmission",
    "entries_digest",
    "evaluate_admission",
    "normalize_entries",
]
