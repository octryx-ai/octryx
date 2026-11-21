"""Helm charts and raw Kubernetes manifests: deployment nodes and ``deploys`` edges."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...store import upsert_edge, upsert_node
from ..common import slugify
from .images import _upsert_image_node


async def _ingest_chart(
    db: AsyncSession, *, project_id: str | None, chart: dict[str, Any], name: str, repo_node: Any,
    repository: str, source_ref: str,
) -> tuple[int, int]:
    nodes = edges = 0
    images = [img for img in (chart.get("images") or []) if isinstance(img, dict) and img.get("image")]
    image_list = ", ".join(
        f"{img['image']}" + (f" {img['version']}" if img.get("version") else "") for img in images
    )
    description = str(chart.get("description") or "").strip()
    chart_node = await upsert_node(
        db,
        project_id=project_id,
        node_type="deployment",
        node_key=slugify(f"deploy-{repository}-{name}"),
        display_name=name,
        description=f"Helm chart {name} in {repository}"
        + (f": {description}" if description else "")
        + (f". Deploys images: {image_list}" if image_list else ""),
        aliases=[name],
        properties={"repository": repository, "path": chart.get("path"), "chart_version": chart.get("version")},
        source_refs=[source_ref],
        resolve_by_alias=False,
    )
    nodes += 1
    await upsert_edge(
        db,
        project_id=project_id,
        edge_type="part_of",
        source_node_id=chart_node.id,
        target_node_id=repo_node.id,
        description=f"Helm chart {name} part of {repository}",
        source_refs=[source_ref],
    )
    edges += 1
    for img in images:
        image_node = await _upsert_image_node(
            db, project_id=project_id, image=str(img["image"]), source_ref=source_ref
        )
        nodes += 1
        await upsert_edge(
            db,
            project_id=project_id,
            edge_type="deploys",
            source_node_id=chart_node.id,
            target_node_id=image_node.id,
            description=f"{name} deploys {img['image']}"
            + (f" version {img['version']}" if img.get("version") else ""),
            source_refs=[source_ref],
        )
        edges += 1
    return nodes, edges


async def _ingest_helm_charts(
    db: AsyncSession, *, project_id: str | None, record: dict[str, Any], repo_node: Any, repository: str,
    source_ref: str,
) -> tuple[int, int]:
    nodes = edges = 0
    for chart in record.get("helm_charts") or []:
        if not isinstance(chart, dict):
            continue
        name = str(chart.get("name") or "").strip()
        if not name:
            continue
        added_nodes, added_edges = await _ingest_chart(
            db, project_id=project_id, chart=chart, name=name, repo_node=repo_node, repository=repository,
            source_ref=source_ref,
        )
        nodes += added_nodes
        edges += added_edges
    return nodes, edges


async def _ingest_k8s_images(
    db: AsyncSession, *, project_id: str | None, record: dict[str, Any], repo_node: Any, repository: str,
    source_ref: str,
) -> tuple[int, int]:
    nodes = edges = 0
    for entry in record.get("k8s_images") or []:
        if not isinstance(entry, dict) or not entry.get("image"):
            continue
        image_node = await _upsert_image_node(
            db, project_id=project_id, image=str(entry["image"]), source_ref=source_ref
        )
        nodes += 1
        workload = str(entry.get("workload") or "").strip()
        await upsert_edge(
            db,
            project_id=project_id,
            edge_type="deploys",
            source_node_id=repo_node.id,
            target_node_id=image_node.id,
            description=f"{repository} deploys {entry['image']}"
            + (f" as {workload}" if workload else "")
            + (f" ({entry.get('manifest')})" if entry.get("manifest") else ""),
            source_refs=[source_ref],
        )
        edges += 1
    return nodes, edges
