"""Model-facing names of operation parameters, and the name each one is sent under (its wire name)."""

from __future__ import annotations

import hashlib
import re
from typing import Any

TOOL_PARAM_NAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")
MAX_NAME = 64
ODATA_PREFIX = "odata_"
_INVALID_CHARS = re.compile(r"[^a-zA-Z0-9_.-]+")


def _fit(name: str, original: str) -> str:
    if len(name) <= MAX_NAME:
        return name
    digest = hashlib.sha256(original.encode()).hexdigest()[:6]
    return f"{name[: MAX_NAME - 7]}_{digest}"


def _candidate(original: str) -> tuple[str, bool]:
    odata = original.startswith("$")
    stripped = original.lstrip("$") if odata else original
    cleaned = _INVALID_CHARS.sub("_", stripped).strip("_") or "param"
    return _fit(cleaned, original), odata


def model_names(wire_names: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    taken: set[str] = set()
    for name in wire_names:
        if TOOL_PARAM_NAME_RE.fullmatch(name) and name not in taken:
            mapping[name] = name
            taken.add(name)
    for name in wire_names:
        if name in mapping:
            continue
        alias, odata = _candidate(name)
        if alias in taken:
            alias = _fit(f"{ODATA_PREFIX}{alias}", name) if odata else alias
        base, counter = alias, 2
        while alias in taken:
            alias = _fit(f"{base}_{counter}", f"{name}#{counter}")
            counter += 1
        mapping[name] = alias
        taken.add(alias)
    return mapping


def alias_parameters(parameters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wires = [str(param.get("wire_name") or param["name"]) for param in parameters]
    mapping = model_names([str(param["name"]) for param in parameters])
    aliased = []
    for param, wire in zip(parameters, wires, strict=True):
        name = mapping[str(param["name"])]
        entry = {**param, "name": name}
        entry.pop("wire_name", None)
        if wire != name:
            entry["wire_name"] = wire
        aliased.append(entry)
    return aliased


__all__ = ["MAX_NAME", "ODATA_PREFIX", "TOOL_PARAM_NAME_RE", "alias_parameters", "model_names"]
