"""Repository manifest knowledge-graph ingestion (library/container_image/deployment nodes,
superseding build/pipeline claims).

The records are built by hand in the manifest scan's record shape.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.knowledge_graph import get_claims_for_node, get_neighbors, resolve_node_by_alias
from app.services.knowledge_graph.extractors import ingest_repository_manifest


def _manifest_record(repository: str) -> dict:
    return {
        "repository": repository,
        "dependencies": [
            {
                "name": "io.netty:netty-handler",
                "artifact": "netty-handler",
                "ecosystem": "maven",
                "manifest": "pom.xml",
                "version": "4.2.15.Final",
            },
            {
                "name": "com.microsoft.sqlserver:mssql-jdbc",
                "artifact": "mssql-jdbc",
                "ecosystem": "maven",
                "manifest": "pom.xml",
                "version": "13.4.0",
            },
        ],
        "containers": [
            {
                "path": "Dockerfile",
                "base_images": [
                    "registry.example.com/library/python:3.12-slim",
                    "registry.example.com/distroless/java21:latest",
                ],
                "runtime_base_image": "registry.example.com/distroless/java21:latest",
                "stages": ["build"],
                "exposed_ports": ["8080"],
                "entrypoint": "java -jar app.jar",
            }
        ],
        "pipelines": [{"kind": "jenkins", "path": "ci/Jenkinsfile", "stages": ["Build", "Push to ECR"]}],
        "helm_charts": [
            {
                "name": "orders-stack",
                "path": "orders-stack",
                "version": "1.2.0",
                "description": "Orders deployment stack",
                "images": [{"key": "orders", "image": "orders-service", "version": "2.0.1"}],
            }
        ],
        "k8s_images": [],
        "terraform_stacks": [],
    }


def _terraform_record(repository: str) -> dict:
    main_tf = "terraform/database/main.tf"
    return {
        "repository": repository,
        "dependencies": [],
        "containers": [],
        "pipelines": [],
        "helm_charts": [],
        "k8s_images": [],
        "terraform_stacks": [
            {
                "path": "terraform/database",
                "providers": ["aws"],
                "data_source_types": [],
                "modules": [
                    {"name": "aurora_serverless", "source": "s3::https://registry.example.com/rds-aurora-v2.15.0.zip"}
                ],
                "resources": [
                    {"address": "aws_db_proxy.aurora", "type": "aws_db_proxy", "name": "aurora", "file": main_tf},
                    {
                        "address": "aws_security_group.rds_proxy",
                        "type": "aws_security_group",
                        "name": "rds_proxy",
                        "file": main_tf,
                    },
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_ingest_repository_manifest_maps_libraries_images_and_claims(db):
    token = uuid.uuid4().hex[:8]
    repository = f"ACME/orders-{token}"
    record = _manifest_record(repository)

    counts = await ingest_repository_manifest(db, project_id=None, record=record)
    assert counts is not None and counts["edges"] >= 5

    # Library shared across repos: a SECOND repo depending on the same lib
    # resolves to the SAME node.
    second = dict(record, repository=f"ACME/billing-{token}")
    await ingest_repository_manifest(db, project_id=None, record=second)
    library = await resolve_node_by_alias(db, project_id=None, alias="io.netty:netty-handler")
    assert library is not None and library.node_type == "library"

    neighbors = await get_neighbors(db, node_id=library.id, limit=50)
    dependents = {
        (n.get("node") or {}).get("display_name")
        for n in neighbors
        if n.get("edge_type") == "depends_on"
    }
    assert repository in dependents and f"ACME/billing-{token}" in dependents

    image = await resolve_node_by_alias(db, project_id=None, alias="distroless/java21")
    assert image is not None and image.node_type == "container_image"

    repo_node = await resolve_node_by_alias(db, project_id=None, alias=repository)
    claims = await get_claims_for_node(db, node_id=repo_node.id)
    by_type = {}
    for claim in claims:
        by_type.setdefault(claim.claim_type, []).append(claim.statement)
    assert any("distroless/java21" in s for s in by_type.get("container_build", []))
    assert any("Build, Push to ECR" in s for s in by_type.get("ci_pipeline", []))

    # Re-ingest supersedes: still exactly one claim per type.
    await ingest_repository_manifest(db, project_id=None, record=record)
    claims = await get_claims_for_node(db, node_id=repo_node.id)
    assert len([c for c in claims if c.claim_type == "ci_pipeline"]) == 1
    assert len([c for c in claims if c.claim_type == "container_build"]) == 1

    # Helm chart deploys edge reaches the container image node.
    chart_node = await resolve_node_by_alias(db, project_id=None, alias="orders-stack")
    assert chart_node is not None and chart_node.node_type == "deployment"
    chart_neighbors = await get_neighbors(db, node_id=chart_node.id, limit=20)
    deployed = {
        (n.get("node") or {}).get("display_name")
        for n in chart_neighbors
        if n.get("edge_type") == "deploys"
    }
    assert "orders-service" in deployed


@pytest.mark.asyncio
async def test_ingest_repository_manifest_maps_terraform_stacks(db):
    token = uuid.uuid4().hex[:8]
    repository = f"ACME/infra-{token}"
    record = _terraform_record(repository)

    counts = await ingest_repository_manifest(db, project_id=None, record=record)
    assert counts is not None

    stack = await resolve_node_by_alias(db, project_id=None, alias="terraform/database")
    assert stack is not None and stack.node_type == "infrastructure_stack"
    # The description is the weak-model-readable summary of what it provisions.
    assert "aws_db_proxy.aurora" in stack.description
    assert "aurora_serverless" in stack.description

    neighbors = await get_neighbors(db, node_id=stack.id, limit=20)
    part_of_repo = [
        n for n in neighbors
        if n.get("edge_type") == "part_of" and (n.get("node") or {}).get("display_name") == repository
    ]
    assert part_of_repo
    # Terraform resource nodes attach to the stack and stay alias-addressable.
    resource = await resolve_node_by_alias(db, project_id=None, alias="aws_db_proxy.aurora")
    assert resource is not None and resource.node_type == "resource"
    resource_neighbors = await get_neighbors(db, node_id=resource.id, limit=10)
    assert any(
        n.get("edge_type") == "part_of" and (n.get("node") or {}).get("id") == stack.id
        for n in resource_neighbors
    )
