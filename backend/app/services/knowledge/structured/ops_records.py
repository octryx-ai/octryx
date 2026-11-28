"""Operations records as typed nodes and edges, from their structured fields only."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime

from .facts import Extraction, NodeRef, SpanRef, clip
from .profile_types import StructuredProfile
from .tickets import NODE_JIRA, ticket_key, ticket_mentions

_HEADING = re.compile(r"\A\s*# (?P<number>[A-Z][A-Z0-9]*(?:-[0-9]+|[0-9]+)): (?P<title>[^\n]*)")
_FACT = re.compile(r"^- (?P<label>[A-Za-z][A-Za-z /]{0,40}): (?P<value>[^\n]+)$", re.MULTILINE)
_JIRA_KEY = re.compile(r"^[A-Z][A-Z0-9]{1,30}-[0-9]{1,7}$")
_SN_FIELDS = {"State": "state", "Problem state": "problem_state", "Priority": "priority", "Impact": "impact",
              "Urgency": "urgency", "Category": "category", "Subcategory": "subcategory", "Close code": "close_code",
              "Known error": "known_error"}
_SN_TIMES = {"Opened": "opened_at", "Resolved": "resolved_at", "Closed": "closed_at"}
_JIRA_FIELDS = {"Type": "type", "Status": "status", "Priority": "priority", "Resolution": "resolution"}
_CONTAINER = re.compile(r"([\w.-]+) \(([^()\s]+)\)")

Cite = Callable[[int], SpanRef]


def _facts(text: str) -> dict[str, tuple[str, int]]:
    head = text.split("\n## ", 1)[0]
    return {m.group("label"): (m.group("value").strip(), m.start()) for m in _FACT.finditer(head)}


def _timestamp(value: str) -> str | None:
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value.strip(), pattern).isoformat()
        except ValueError:
            continue
    return None


def _ticket(extraction: Extraction, node_type: str, number: str, cite: SpanRef) -> NodeRef:
    return extraction.node(node_type, ticket_key(node_type, number), number, cite, number=number, stub=True)


def _mentions(extraction, record: NodeRef, text: str, own: str, cite: Cite, profile, jira, causes=frozenset()):
    for node_type, number, offset in ticket_mentions(text, profile, jira)[: profile.max_mentions_per_record + 1]:
        if number == own:
            continue
        target = _ticket(extraction, node_type, number, cite(offset))
        kind = "caused_by" if number in causes else "mentions"
        extraction.edge(kind, record, target, cite(offset))


def extract_servicenow(text: str, cite: Cite, profile: StructuredProfile, jira) -> Extraction:
    extraction = Extraction()
    heading = _HEADING.match(text)
    facts = _facts(text)
    table = facts.get("Table", ("", 0))[0]
    number = heading.group("number") if heading is not None else ""
    node_type = next((kind for kind, pattern in profile.ticket_patterns if pattern.fullmatch(number)), None)
    if heading is None or node_type is None:
        extraction.warn("record_shape_unknown")
        return extraction
    title = heading.group("title").strip()
    first = cite(heading.start("number"))
    props = {"number": number, "title": clip(title, 200), "table": table, "stub": False}
    props.update({key: facts[label][0] for label, key in _SN_FIELDS.items() if label in facts})
    props.update({key: _timestamp(facts[label][0]) for label, key in _SN_TIMES.items() if label in facts})
    record = extraction.node(node_type, ticket_key(node_type, number), f"{number} {clip(title, 80)}", first, **props)
    for label, edge, target_type, prefix in (
        ("Assignment group", "assigned_to_group", "AssignmentGroup", "group"),
        ("Business service", "affects_service", "Service", "service"),
        ("Configuration item", "affects_ci", "ConfigurationItem", "ci"),
    ):
        if label in facts:
            value, offset = facts[label]
            target = extraction.node(target_type, f"{prefix}:{value}", value, cite(offset), name=value)
            extraction.edge(edge, record, target, cite(offset))
    causes = {m.group(1) for pattern in profile.caused_by_patterns for m in pattern.finditer(text)}
    _mentions(extraction, record, text, number, cite, profile, jira, frozenset(causes))
    return extraction


def _listed(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def extract_jira(text: str, cite: Cite, profile: StructuredProfile, jira) -> Extraction:
    extraction = Extraction()
    heading = _HEADING.match(text)
    if heading is None or not _JIRA_KEY.fullmatch(heading.group("number")):
        extraction.warn("record_shape_unknown")
        return extraction
    key, title = heading.group("number"), heading.group("title").strip()
    project = key.rsplit("-", 1)[0]
    facts = _facts(text)
    props = {"number": key, "title": clip(title, 200), "stub": False}
    props.update({name: facts[label][0] for label, name in _JIRA_FIELDS.items() if label in facts})
    if "Labels" in facts:
        props["labels"] = _listed(facts["Labels"][0])
    if "Created" in facts:
        props["created_at"] = _timestamp(facts["Created"][0])
    issue = extraction.node(NODE_JIRA, ticket_key(NODE_JIRA, key), f"{key} {clip(title, 80)}",
                            cite(heading.start("number")), **props)
    for label, edge, target_type, prefix in (
        ("Components", "in_component", "JiraComponent", "jira-component"),
        ("Fix versions", "released_in", "Version", "jira-version"),
        ("Affects versions", "affects_version", "Version", "jira-version"),
    ):
        if label not in facts:
            continue
        value, offset = facts[label]
        for name in _listed(value):
            target = extraction.node(target_type, f"{prefix}:{project}/{name}", name, cite(offset),
                                     name=name, project=project)
            extraction.edge(edge, issue, target, cite(offset))
    _mentions(extraction, issue, text, key, cite, profile, jira)
    return extraction


def _image(reference: str) -> tuple[str, str] | None:
    name = reference.split("@", 1)[0].rsplit("/", 1)[-1]
    repository, _, tag = name.partition(":")
    return (repository, tag) if repository and tag else None


def extract_inventory(text: str, cite: Cite, profile: StructuredProfile) -> Extraction:
    extraction = Extraction()
    heading = profile.inventory_namespace_pattern.match(text)
    cluster_match = profile.inventory_cluster_pattern.search(text)
    if heading is None or cluster_match is None:
        extraction.warn("inventory_shape_unknown")
        return extraction
    namespace_name, cluster_name = heading.group("namespace"), cluster_match.group("cluster")
    cluster = extraction.node("Cluster", f"k8s-cluster:{cluster_name}", cluster_name,
                              cite(cluster_match.start("cluster")), name=cluster_name)
    namespace = extraction.node("Namespace", f"k8s-namespace:{cluster_name}/{namespace_name}", namespace_name,
                                cite(heading.start("namespace")), name=namespace_name, cluster=cluster_name)
    extraction.edge("runs_in", namespace, cluster, cite(heading.start("namespace")))
    header: list[str] | None = None
    offset = 0
    for line in text.split("\n"):
        start, offset = offset, offset + len(line) + 1
        if not line.startswith("|"):
            header = None if not line.strip() else header
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and cells[0] == "Deployment":
            header = cells
            continue
        if header is None or set("".join(cells)) <= set("-: "):
            continue
        row = dict(zip(header, cells, strict=False))
        name = row.get("Deployment", "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", name):
            continue
        deployment = extraction.node(
            "Deployment", f"k8s-deployment:{cluster_name}/{namespace_name}/{name}", name, cite(start), name=name,
            namespace=namespace_name, cluster=cluster_name, desired=row.get("Desired replicas"),
            ready=row.get("Ready"), available=row.get("Available"),
        )
        extraction.edge("runs_in", deployment, namespace, cite(start))
        containers = next((value for column, value in row.items() if column.startswith("Containers")), "")
        for container, reference in _CONTAINER.findall(containers):
            parsed = _image(reference)
            if parsed is None:
                continue
            repository, tag = parsed
            image = extraction.node("Version", f"image:{repository}:{tag}", f"{repository}:{tag}", cite(start),
                                    repository=repository, tag=tag)
            extraction.edge("uses_image", deployment, image, cite(start), container=container)
    return extraction


__all__ = ["extract_inventory", "extract_jira", "extract_servicenow"]
