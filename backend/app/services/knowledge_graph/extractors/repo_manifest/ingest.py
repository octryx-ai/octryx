"""Map one ``repository_manifest`` record into the graph."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...store import replace_claims_of_type, upsert_node
from ..common import slugify
from .containers import _ingest_containers, _pipeline_claims
from .deployments import _ingest_helm_charts, _ingest_k8s_images
from .libraries import _ingest_libraries
from .terraform import _ingest_terraform_stacks


async def ingest_repository_manifest(
    db: AsyncSession, *, project_id: str | None, record: dict[str, Any]
) -> dict[str, int] | None:
    repository = str(record.get("repository") or record.get("label") or "").strip()
    if not repository:
        return None
    source_ref = f"repo:{repository}"
    repo_node = await upsert_node(
        db,
        project_id=project_id,
        node_type="repository",
        node_key=slugify(f"repo-{repository}"),
        display_name=repository,
        description="",
        aliases=[repository, repository.split("/")[-1]],
    )
    scope = {
        "project_id": project_id, "record": record, "repo_node": repo_node, "repository": repository,
        "source_ref": source_ref,
    }
    nodes, edges = await _ingest_libraries(db, **scope)
    added_nodes, added_edges, build_claims = await _ingest_containers(db, **scope)
    nodes, edges = nodes + added_nodes, edges + added_edges
    pipeline_claims = _pipeline_claims(record, source_ref)
    for step in (_ingest_helm_charts, _ingest_k8s_images, _ingest_terraform_stacks):
        added_nodes, added_edges = await step(db, **scope)
        nodes, edges = nodes + added_nodes, edges + added_edges

    await replace_claims_of_type(
        db,
        project_id=project_id,
        subject_node_id=repo_node.id,
        claim_type="container_build",
        claims=build_claims,
    )
    await replace_claims_of_type(
        db,
        project_id=project_id,
        subject_node_id=repo_node.id,
        claim_type="ci_pipeline",
        claims=pipeline_claims,
    )
    return {"nodes": nodes, "edges": edges, "claims": len(build_claims) + len(pipeline_claims)}
