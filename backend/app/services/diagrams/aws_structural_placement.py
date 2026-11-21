"""Placement of AWS topology nodes into VPC, subnet-tier and regional containers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .aws_overview_curation import curate_overview
from .aws_structural_styles import (
    _EXCLUDED_NODE_TYPES,
    _KEPT_EDGE_TYPES,
    _KEPT_RESOURCE_BELONGS_TO_TYPES,
    _PULLED_INTO_VPC_TYPES,
    _SUBNET_TIER_STYLES,
)


@dataclass
class StructuralPlacement:
    nodes_by_ref: dict[str, dict[str, Any]]
    type_by_ref: dict[str, str]
    vpc_refs: list[str]
    endpoint: Callable[[dict[str, Any], str], str]
    inter_vpc_refs: dict[str, list[str]]
    excluded: set[str]
    curation_notes: list[str]
    subnet_tier: dict[str, str]
    tier_of_vpc: dict[str, dict[str, list[str]]]
    tier_children: dict[tuple[str, str], list[str]]
    vpc_children: dict[str, list[str]]
    regional: list[str]


def build_structural_placement(
    selected_nodes: list[dict[str, Any]],
    selected_edges: list[dict[str, Any]],
    node_refs: dict[int, str],
) -> StructuralPlacement | None:
    nodes_by_ref = {node_refs[id(node)]: node for node in selected_nodes}
    type_by_ref = {ref: str(node.get("type") or "") for ref, node in nodes_by_ref.items()}
    vpc_refs = [ref for ref, t in type_by_ref.items() if t == "vpc"]
    if not vpc_refs:
        return None

    endpoint = _endpoint_resolver(nodes_by_ref)
    subnet_vpc, resource_subnets, resource_vpc_sets = _membership_from_edges(selected_edges, endpoint, type_by_ref)

    resource_vpc, inter_vpc_refs = _split_vpc_wiring(resource_vpc_sets)
    excluded = {ref for ref, t in type_by_ref.items() if t in _EXCLUDED_NODE_TYPES}
    kept_triples = [
        (source, target, edge_type)
        for source, target, edge_type, _edge in _iter_kept_edges(
            selected_edges, endpoint, type_by_ref, nodes_by_ref, excluded
        )
    ]
    curation_notes = curate_overview(
        nodes_by_ref=nodes_by_ref,
        type_by_ref=type_by_ref,
        kept_edges=kept_triples,
        resource_vpc=resource_vpc,
    )

    # Real AWS resources span every AZ of a tier (3 subnets, one per zone), so
    # subnet-exact placement leaves every subnet empty. Group subnets by tier
    # instead and place a resource in its tier container when all of its subnets
    # share one tier. Tiers keyed per VPC: (vpc_ref, tier).
    subnet_tier = {
        ref: _subnet_tier(nodes_by_ref[ref])
        for ref, t in type_by_ref.items()
        if t == "subnet"
    }
    tier_of_vpc = _tier_membership(subnet_vpc, subnet_tier, vpc_refs)
    placed_in_tier, tier_children = _tier_placement(
        resource_subnets, nodes_by_ref, type_by_ref, excluded, subnet_tier, subnet_vpc
    )
    vpc_children, regional = _vpc_and_regional_children(
        nodes_by_ref, type_by_ref, vpc_refs, excluded, placed_in_tier, inter_vpc_refs, resource_vpc,
        resource_subnets, subnet_vpc,
    )

    kept_pairs = [(source, target) for source, target, _edge_type in kept_triples]
    _pull_wired_nodes_into_vpc(kept_pairs, type_by_ref, placed_in_tier, vpc_children, regional)
    return StructuralPlacement(
        nodes_by_ref, type_by_ref, vpc_refs, endpoint, inter_vpc_refs, excluded, curation_notes,
        subnet_tier, tier_of_vpc, tier_children, vpc_children, regional,
    )


def _split_vpc_wiring(
    resource_vpc_sets: dict[str, set[str]],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    # A node wired to one VPC nests inside it; a node wired to several VPCs
    # (peering connection, transit gateway) is an inter-VPC connector drawn
    # between the VPC containers instead of inside one of them.
    resource_vpc = {
        ref: next(iter(vpcs)) for ref, vpcs in resource_vpc_sets.items() if len(vpcs) == 1
    }
    inter_vpc_refs = {
        ref: sorted(vpcs) for ref, vpcs in resource_vpc_sets.items() if len(vpcs) > 1
    }
    return resource_vpc, inter_vpc_refs


def _endpoint_resolver(nodes_by_ref: dict[str, dict[str, Any]]) -> Callable[[dict[str, Any], str], str]:
    ref_by_node_id = {
        str(node.get("id") or "").strip(): ref
        for ref, node in nodes_by_ref.items()
        if str(node.get("id") or "").strip()
    }

    def _endpoint(edge: dict[str, Any], side: str) -> str:
        ref = str(edge.get(f"{side}_ref") or "").strip()
        if ref in nodes_by_ref:
            return ref
        return ref_by_node_id.get(str(edge.get(side) or "").strip(), "")

    return _endpoint


def _membership_from_edges(
    selected_edges: list[dict[str, Any]],
    endpoint: Callable[[dict[str, Any], str], str],
    type_by_ref: dict[str, str],
) -> tuple[dict[str, str], dict[str, set[str]], dict[str, set[str]]]:
    subnet_vpc: dict[str, str] = {}
    resource_subnets: dict[str, set[str]] = {}
    resource_vpc_sets: dict[str, set[str]] = {}
    for edge in selected_edges:
        source, target = endpoint(edge, "source"), endpoint(edge, "target")
        if not source or not target:
            continue
        edge_type = str(edge.get("type") or "")
        source_type, target_type = type_by_ref.get(source, ""), type_by_ref.get(target, "")
        if edge_type == "belongs_to" and source_type == "subnet" and target_type == "vpc":
            subnet_vpc[source] = target
        elif edge_type in {"uses_subnet", "runs_in"} and target_type == "subnet":
            resource_subnets.setdefault(source, set()).add(target)
        elif edge_type in {"runs_in", "attached_to", "belongs_to"} and target_type == "vpc":
            resource_vpc_sets.setdefault(source, set()).add(target)
    return subnet_vpc, resource_subnets, resource_vpc_sets


def _tier_placement(
    resource_subnets: dict[str, set[str]],
    nodes_by_ref: dict[str, dict[str, Any]],
    type_by_ref: dict[str, str],
    excluded: set[str],
    subnet_tier: dict[str, str],
    subnet_vpc: dict[str, str],
) -> tuple[dict[str, tuple[str, str]], dict[tuple[str, str], list[str]]]:
    placed_in_tier: dict[str, tuple[str, str]] = {}
    for ref, subnets in resource_subnets.items():
        if ref not in nodes_by_ref or ref in excluded:
            continue
        tiers = {subnet_tier[s] for s in subnets if s in subnet_tier}
        vpcs = {subnet_vpc[s] for s in subnets if s in subnet_vpc}
        if len(tiers) == 1 and len(vpcs) == 1:
            placed_in_tier[ref] = (next(iter(vpcs)), next(iter(tiers)))

    tier_children: dict[tuple[str, str], list[str]] = {}
    for ref, tier_key in list(placed_in_tier.items()):
        if type_by_ref.get(ref) in {"vpc", "subnet"}:
            placed_in_tier.pop(ref, None)
            continue
        tier_children.setdefault(tier_key, []).append(ref)
    return placed_in_tier, tier_children


def _vpc_and_regional_children(
    nodes_by_ref: dict[str, dict[str, Any]],
    type_by_ref: dict[str, str],
    vpc_refs: list[str],
    excluded: set[str],
    placed_in_tier: dict[str, tuple[str, str]],
    inter_vpc_refs: dict[str, list[str]],
    resource_vpc: dict[str, str],
    resource_subnets: dict[str, set[str]],
    subnet_vpc: dict[str, str],
) -> tuple[dict[str, list[str]], list[str]]:
    vpc_children: dict[str, list[str]] = {ref: [] for ref in vpc_refs}
    regional: list[str] = []
    for ref in nodes_by_ref:
        if ref in excluded or ref in placed_in_tier or type_by_ref[ref] in {"vpc", "subnet"}:
            continue
        if ref in inter_vpc_refs:
            continue
        vpc = resource_vpc.get(ref) or _single_vpc_via_subnets(ref, resource_subnets, subnet_vpc)
        if vpc in vpc_children:
            vpc_children[vpc].append(ref)
        else:
            regional.append(ref)
    return vpc_children, regional


def _subnet_tier(node: dict[str, Any]) -> str:
    tier = str(((node.get("attributes")) or {}).get("subnet_tier") or "").strip().lower()
    return tier if tier in _SUBNET_TIER_STYLES else "other"


def _tier_membership(
    subnet_vpc: dict[str, str],
    subnet_tier: dict[str, str],
    vpc_refs: list[str],
) -> dict[str, dict[str, list[str]]]:
    membership: dict[str, dict[str, list[str]]] = {ref: {} for ref in vpc_refs}
    for subnet_ref, vpc_ref in subnet_vpc.items():
        if vpc_ref not in membership:
            continue
        tier = subnet_tier.get(subnet_ref, "other")
        membership[vpc_ref].setdefault(tier, []).append(subnet_ref)
    return membership


def _iter_kept_edges(
    selected_edges: list[dict[str, Any]],
    endpoint: Any,
    type_by_ref: dict[str, str],
    nodes_by_ref: dict[str, dict[str, Any]],
    excluded: set[str],
):
    seen: set[tuple[str, str, str]] = set()
    for edge in selected_edges:
        edge_type = str(edge.get("type") or "")
        source, target = endpoint(edge, "source"), endpoint(edge, "target")
        if not source or not target or source == target:
            continue
        if source in excluded or target in excluded:
            continue
        if source not in nodes_by_ref or target not in nodes_by_ref:
            continue
        pair_types = (type_by_ref.get(source, ""), type_by_ref.get(target, ""))
        keep = edge_type in _KEPT_EDGE_TYPES or (
            edge_type == "belongs_to" and pair_types in _KEPT_RESOURCE_BELONGS_TO_TYPES
        )
        if not keep:
            continue
        key = (source, target, edge_type)
        if key in seen:
            continue
        seen.add(key)
        yield source, target, edge_type, edge


def _pull_wired_nodes_into_vpc(
    kept_pairs: list[tuple[str, str]],
    type_by_ref: dict[str, str],
    placed_in_tier: dict[str, tuple[str, str]],
    vpc_children: dict[str, list[str]],
    regional: list[str],
) -> None:
    vpc_of: dict[str, str] = {}
    for vpc_ref, children in vpc_children.items():
        for ref in children:
            vpc_of[ref] = vpc_ref
    for ref, (vpc_ref, _tier) in placed_in_tier.items():
        vpc_of[ref] = vpc_ref

    regional_set = set(regional)
    for source, target in kept_pairs:
        for candidate, other in ((source, target), (target, source)):
            if candidate not in regional_set:
                continue
            if type_by_ref.get(candidate, "") not in _PULLED_INTO_VPC_TYPES:
                continue
            vpc = vpc_of.get(other)
            if not vpc:
                continue
            regional_set.discard(candidate)
            vpc_children[vpc].append(candidate)
            vpc_of[candidate] = vpc
    regional[:] = [ref for ref in regional if ref in regional_set]


def _single_vpc_via_subnets(
    ref: str,
    resource_subnets: dict[str, set[str]],
    subnet_vpc: dict[str, str],
) -> str:
    vpcs = {subnet_vpc[s] for s in resource_subnets.get(ref, set()) if s in subnet_vpc}
    return next(iter(vpcs)) if len(vpcs) == 1 else ""
