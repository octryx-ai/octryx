"""Deterministic Terraform (HCL) parser for code structure snapshots."""

from __future__ import annotations

import re
from typing import Any

_BLOCK_HEADER = re.compile(
    r"^\s*(resource|data|module|variable|output)\s+"
    r"\"([A-Za-z0-9_.-]+)\"(?:\s+\"([A-Za-z0-9_.-]+)\")?\s*\{"
)
_TOP_LEVEL_KEY = re.compile(r"^\s*([A-Za-z_][\w-]*)\s*(?:=|\{)")
# Literal address grammar. Order matters: the qualified forms consume their
# prefix so `data.aws_ami.x` never double-matches as `aws_ami.x`; the generic
# resource form requires an underscore in the type segment (all provider
# resource types have one: aws_vpc, azurerm_lb, google_compute_instance),
# which keeps `var.x`, `local.x`, `each.value`, `count.index` out of it.
_REFERENCE = re.compile(
    r"(?<![\w.])(?:"
    r"(data\.[a-z][a-z0-9]*_[a-z0-9_]+\.[A-Za-z0-9_-]+)"
    r"|(module\.[A-Za-z0-9_-]+)"
    r"|(var\.[A-Za-z0-9_-]+)"
    r"|([a-z][a-z0-9]*_[a-z0-9_]+\.[A-Za-z0-9_-]+)"
    r")"
)
_KNOWN_PROVIDER_PREFIXES = ("aws", "azurerm", "google")
# Bounded reference evidence per block: enough for faithful wiring, never an
# unbounded copy of a generated 5000-line resource body.
_MAX_USES_PER_BLOCK = 60
_MAX_FIELDS_PER_BLOCK = 40


def _package_from_path(relative_path: str) -> str:
    parts = relative_path.replace("\\", "/").split("/")
    return ".".join(parts[:-1]) if len(parts) > 1 else ""


def _strip_comments(text: str) -> list[str]:
    without_blocks = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    lines: list[str] = []
    for line in without_blocks.splitlines():
        for marker in ("#", "//"):
            if marker in line:
                line = line.split(marker, 1)[0]
        lines.append(line)
    return lines


def provider_prefix_for_resource_type(resource_type: str) -> str:
    prefix = str(resource_type or "").split("_", 1)[0].lower()
    return prefix if prefix in _KNOWN_PROVIDER_PREFIXES else "other"


def _node_identity(block_kind: str, type_label: str, name_label: str) -> tuple[str, str, str]:
    if block_kind == "resource":
        return "resource", f"{type_label}.{name_label}", type_label
    if block_kind == "data":
        return "data", f"data.{type_label}.{name_label}", type_label
    if block_kind == "module":
        return "module", f"module.{type_label}", ""
    if block_kind == "variable":
        return "variable", f"var.{type_label}", ""
    return "output", f"output.{type_label}", ""


def _finish_block(block: dict[str, Any]) -> dict[str, Any]:
    attributes: dict[str, Any] = {"block": block["kind"]}
    resource_type = block["resource_type"]
    if resource_type:
        attributes["resource_type"] = resource_type
        attributes["provider"] = provider_prefix_for_resource_type(resource_type)
    uses = [candidate for candidate in block["uses"] if candidate != block["name"]]
    return {
        "name": block["name"],
        "kind": block["kind"],
        "extends": [],
        "implements": [],
        # KEY NAMES only — argument values (secrets, IPs, ARNs) never enter
        # the snapshot.
        "fields": block["fields"][:_MAX_FIELDS_PER_BLOCK],
        "methods": [],
        "uses": uses[:_MAX_USES_PER_BLOCK],
        "uses_packages": [],
        "attributes": attributes,
    }


def parse_terraform_hcl(relative_path: str, text: str) -> dict[str, Any]:
    lines = _strip_comments(text)
    types: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    depth = 0
    for line in lines:
        header = _BLOCK_HEADER.match(line) if current is None else None
        if header:
            block_kind, type_label, name_label = header.group(1), header.group(2), header.group(3) or ""
            if block_kind in {"resource", "data"} and not name_label:
                depth += line.count("{") - line.count("}")
                continue
            kind, node_name, resource_type = _node_identity(block_kind, type_label, name_label)
            current = {
                "kind": kind,
                "name": node_name,
                "resource_type": resource_type,
                "depth": depth,
                "fields": [],
                "uses": [],
            }
            depth += line.count("{") - line.count("}")
            if depth <= current["depth"]:  # one-line block, e.g. `variable "x" {}`
                types.append(_finish_block(current))
                current = None
            continue
        if current is not None:
            if depth == current["depth"] + 1:
                key_match = _TOP_LEVEL_KEY.match(line)
                if key_match and key_match.group(1) not in current["fields"]:
                    current["fields"].append(key_match.group(1))
            for match in _REFERENCE.finditer(line):
                candidate = match.group(0)
                if candidate not in current["uses"]:
                    current["uses"].append(candidate)
        depth += line.count("{") - line.count("}")
        if current is not None and depth <= current["depth"]:
            types.append(_finish_block(current))
            current = None
    if current is not None:  # unterminated block at EOF: keep the literal header evidence
        types.append(_finish_block(current))
    return {"package": _package_from_path(relative_path), "imports": [], "types": types}
