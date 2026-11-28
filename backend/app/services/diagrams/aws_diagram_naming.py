"""Deterministic display names for AWS diagram nodes."""

from __future__ import annotations

import re
from typing import Any

_TRAILING_UUID = re.compile(r"-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
# Terraform/EKS generated suffixes: 20+ digits, optionally ending in hex.
_TRAILING_GENERATED = re.compile(r"-\d{18,}[0-9a-f]*$")
# Short generated hash suffixes (k8s load balancer / target group names).
_TRAILING_HASH = re.compile(r"-[0-9a-f]{8,}$")
_BARE_RESOURCE_ID = re.compile(r"^(vpc|subnet|rtb|igw|nat|eni|eipalloc|sg)-([0-9a-f]{8,})$")
# Prefixes added by controllers, stripped only for the matching node types.
_TYPE_PREFIXES = {
    "load_balancer": ("k8s-",),
    "target_group": ("k8s-",),
    "autoscaling_group": ("eks-",),
}


def display_name(node: dict[str, Any]) -> str:
    name_tag = str(node.get("name") or "").strip()
    if name_tag:
        return name_tag
    label = str(node.get("label") or "").strip()
    node_type = str(node.get("type") or "").strip()
    return normalize_label(label, node_type)


def normalize_label(label: str, node_type: str = "") -> str:
    bare_id = _BARE_RESOURCE_ID.match(label)
    if bare_id:
        prefix, digits = bare_id.groups()
        return f"{prefix}-…{digits[-6:]}"

    text = label
    for pattern in (_TRAILING_UUID, _TRAILING_GENERATED, _TRAILING_HASH):
        stripped = pattern.sub("", text)
        if stripped:
            text = stripped
    for prefix in _TYPE_PREFIXES.get(node_type, ()):
        if text.startswith(prefix) and len(text) > len(prefix):
            text = text[len(prefix) :]

    # Controllers join namespace and name; collapse exact duplicates
    # ("traefike-traefike" -> "traefike").
    parts = text.split("-")
    if len(parts) == 2 and parts[0] == parts[1]:
        text = parts[0]
    return text or label
