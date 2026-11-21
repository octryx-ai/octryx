"""Dockerfile base images, container build claims and CI pipeline claims."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...store import upsert_edge
from .images import _normalized_image, _upsert_image_node

_MAX_IMAGES = 60


def _build_claim(container: dict[str, Any], runtime_base: str, path: str, source_ref: str) -> dict[str, Any]:
    parts = [f"Builds container from {runtime_base or 'unknown base'} ({path})"]
    stages = [str(s) for s in (container.get("stages") or []) if str(s).strip()]
    if stages:
        parts.append(f"build stages: {', '.join(stages)}")
    ports = [str(p) for p in (container.get("exposed_ports") or []) if str(p).strip()]
    if ports:
        parts.append(f"exposes {', '.join(ports)}")
    entrypoint = str(container.get("entrypoint") or "").strip()
    if entrypoint:
        parts.append(f"entrypoint: {entrypoint}")
    return {"statement": "; ".join(parts), "source_refs": [source_ref]}


async def _ingest_containers(
    db: AsyncSession, *, project_id: str | None, record: dict[str, Any], repo_node: Any, repository: str,
    source_ref: str,
) -> tuple[int, int, list[dict[str, Any]]]:
    """``(nodes, edges, build claims)``: base-image nodes + a superseding build claim per container."""
    nodes = edges = 0
    build_claims: list[dict[str, Any]] = []
    seen_images: set[str] = set()
    for container in record.get("containers") or []:
        if not isinstance(container, dict):
            continue
        path = str(container.get("path") or "Dockerfile")
        runtime_base = _normalized_image(str(container.get("runtime_base_image") or ""))
        for raw in container.get("base_images") or []:
            image = _normalized_image(str(raw))
            if not image or image in seen_images or len(seen_images) >= _MAX_IMAGES:
                continue
            seen_images.add(image)
            image_node = await _upsert_image_node(db, project_id=project_id, image=image, source_ref=source_ref)
            nodes += 1
            role = "runtime base image" if image == runtime_base else "build-stage image"
            await upsert_edge(
                db,
                project_id=project_id,
                edge_type="based_on",
                source_node_id=repo_node.id,
                target_node_id=image_node.id,
                description=f"{repository} {path}: {role} {image}",
                source_refs=[source_ref],
            )
            edges += 1
        build_claims.append(_build_claim(container, runtime_base, path, source_ref))
    return nodes, edges, build_claims


def _pipeline_claims(record: dict[str, Any], source_ref: str) -> list[dict[str, Any]]:
    """Superseding CI pipeline claims listing the real stages."""
    pipeline_claims: list[dict[str, Any]] = []
    for pipeline in record.get("pipelines") or []:
        if not isinstance(pipeline, dict):
            continue
        stages = [str(s) for s in (pipeline.get("stages") or []) if str(s).strip()]
        path = str(pipeline.get("path") or "").strip()
        kind = str(pipeline.get("kind") or "ci").strip()
        if not stages:
            continue
        pipeline_claims.append(
            {
                "statement": f"CI pipeline {path} ({kind}): stages {', '.join(stages)}",
                "source_refs": [source_ref],
            }
        )
    return pipeline_claims
