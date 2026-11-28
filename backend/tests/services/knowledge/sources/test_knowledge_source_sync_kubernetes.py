"""Source Sync: a Kubernetes cluster's workload inventory as an operations source."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.models import BuiltInToolConfig
from app.models.project.knowledge_evidence import KnowledgeEvidenceSource
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.models.project.knowledge_structured import KnowledgeStructuredEdge, KnowledgeStructuredNode
from app.services.admin.project.named_connection_service import save_named
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ledger.errors import InvalidEvidenceRequestError
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.sources.sync import kubernetes as k8s
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.contract import ConnectorError
from app.services.knowledge.sources.sync.service import configure_connector
from app.services.knowledge.sources.sync.service_run import run_connector
from app.services.knowledge.structured.build import claim_next_build, request_build, sync_layers
from app.services.knowledge.structured.build_slice import run_build_slice
from app.services.knowledge.structured.build_states import TRIGGER_MANUAL
from app.services.knowledge.structured.facts import node_id
from app.services.knowledge.structured.profile import structured_profile
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace

pytestmark = pytest.mark.usefixtures("public_source_dns")

API = "https://k8s.example.test:6443"
TOKEN = "fake-default-token"
NAMED_TOKEN = "fake-named-token"


def _deployment(name: str, image: str, *, version: str = "1", ready: int = 2, env_secret: str = "s3cr3t") -> dict:
    container = {"name": name.split("-")[0], "image": image, "env": [{"name": "DB_PASSWORD", "value": env_secret}],
                 "args": ["--token", env_secret]}
    return {"metadata": {"name": name, "resourceVersion": version, "annotations": {"secret": env_secret}},
            "spec": {"replicas": 2, "template": {"spec": {"containers": [container]}}},
            "status": {"readyReplicas": ready, "availableReplicas": ready}}


class FakeKubernetes:
    def __init__(self) -> None:
        self.namespaces: dict[str, list[dict]] = {
            "shop-test": [_deployment("orders-data-deployment", "ecr.example/shop/baseimage:3.2-3")],
            "prod": [_deployment("orders-access-deployment", "ecr.example/shop/app-server:2.4-285")],
        }
        self.seen: list[tuple[str, str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        self.seen.append((request.url.host, request.url.path, request.headers.get("Authorization", "")))
        if request.url.path == "/api/v1/namespaces":
            assert request.url.params["limit"] == str(k8s.MAX_NAMESPACES)
            return httpx.Response(200, json={"items": [{"metadata": {"name": name}} for name in self.namespaces]})
        namespace = request.url.path.split("/")[5]
        assert request.url.params["limit"] == str(k8s.MAX_DEPLOYMENTS)
        if namespace not in self.namespaces:
            return httpx.Response(404, json={})
        return httpx.Response(200, json={"items": self.namespaces[namespace], "metadata": {}})


async def _workspace(db, *, config: dict | None = None):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    db.add(BuiltInToolConfig(tool_name="kubernetes", project_id=workspace_id, is_active=True,
                             config=config if config is not None else {"k8s_api_url": API, "k8s_token": TOKEN}))
    await db.flush()
    runtime, _, evidence_index = build_runtime()
    return authorized, user_id, runtime


async def _connector(db, authorized, user_id, **scope):
    config = validate_config(connector_key="inventory", kind="kubernetes", **scope)
    return await configure_connector(db, authorized=authorized, config=config, actor_id=user_id)


async def _run(db, authorized, user_id, runtime, row, fake):
    row = await db.get(KnowledgeSourceConnector, row.id)
    return await run_connector(db, runtime=runtime, authorized=authorized, row=row, actor_id=user_id,
                               transport=httpx.MockTransport(fake.handler))


def test_the_scope_is_one_cluster_and_optional_namespaces_on_the_kubernetes_kind_only():
    config = validate_config(connector_key="inv", kind="kubernetes", cluster=" nonprod ",
                             namespaces=["shop-test", "shop-test"])
    assert config.scope == {"cluster": "nonprod", "namespaces": ["shop-test"]}
    assert validate_config(connector_key="inv", kind="kubernetes", cluster="arn:aws:eks:eu-central-1:1:cluster/x"
                           ).scope["namespaces"] == []
    for bad in ({"cluster": None}, {"cluster": "bad cluster"}, {"cluster": "c", "namespaces": ["Bad_NS"]},
                {"cluster": "c", "namespaces": [f"ns-{n}" for n in range(51)]}, {"cluster": "c", "spaces": ["X"]}):
        with pytest.raises(InvalidEvidenceRequestError):
            validate_config(connector_key="inv", kind="kubernetes", **bad)
    with pytest.raises(InvalidEvidenceRequestError):
        validate_config(connector_key="inv", kind="jira", project_keys=["OPS"], cluster="c")


def test_an_inventory_holds_names_counts_and_images_and_never_environment_or_arguments():
    deployments = [k8s.deployment_of(_deployment("b-deployment", "img/b:2")),
                   k8s.deployment_of(_deployment("a-deployment", "img/a:1", ready=0))]
    text = k8s.render_inventory("nonprod", "shop-test", deployments, truncated=True).decode()
    assert text == (
        "# Kubernetes inventory: namespace shop-test\n\nCluster: nonprod\n\n"
        "## Deployments in shop-test (2)\n\n"
        "The cluster lists more deployments; only the first 500 deployments are listed.\n\n"
        "| Deployment | Desired replicas | Ready | Available | Containers (image) |\n|---|---|---|---|---|\n"
        "| a-deployment | 2 | 0 | 0 | a (img/a:1) |\n| b-deployment | 2 | 2 | 2 | b (img/b:2) |\n"
    )
    assert "s3cr3t" not in text and "DB_PASSWORD" not in text
    assert k8s.inventory_marker(deployments, False) != k8s.inventory_marker(deployments, True)
    changed = [k8s.deployment_of(_deployment("a-deployment", "img/a:1", version="2"))]
    assert k8s.inventory_marker(changed, False) != k8s.inventory_marker(deployments[1:], False)
    with pytest.raises(ConnectorError):
        k8s.deployment_of({"metadata": {"name": "Not A Name"}})


async def test_a_sync_creates_one_inventory_per_namespace_and_follows_changes(db):
    authorized, user_id, runtime = await _workspace(db)
    row = await _connector(db, authorized, user_id, cluster="nonprod")
    fake = FakeKubernetes()
    first = await _run(db, authorized, user_id, runtime, row, fake)
    assert first.state == "completed" and first.report["created"] == 2
    assert {auth for _, _, auth in fake.seen} == {f"Bearer {TOKEN}"}
    keys = set((await db.execute(select(KnowledgeEvidenceSource.source_key).where(
        KnowledgeEvidenceSource.project_id == authorized.project_id))).scalars())
    assert keys == {"kubernetes.inventory.prod", "kubernetes.inventory.shop-test"}
    again = await _run(db, authorized, user_id, runtime, row, fake)
    assert again.report["created"] == 0 and again.report.get("updated", 0) == 0
    fake.namespaces["shop-test"] = [_deployment("orders-data-deployment", "ecr.example/shop/baseimage:3.2-4", version="9")]
    del fake.namespaces["prod"]
    changed = await _run(db, authorized, user_id, runtime, row, fake)
    assert changed.report["updated"] == 1 and changed.report["retired"] == 1


async def test_a_named_connection_bound_to_the_cluster_reads_only_its_namespaces(db):
    authorized, user_id, runtime = await _workspace(db)
    await save_named(db, connector="kubernetes", project_id=authorized.project_id, actor_id=user_id, payload={
        "name": "prod", "bound_scopes": ["prod-cluster"], "k8s_api_url": "https://prod.example.test",
        "k8s_token": NAMED_TOKEN, "k8s_allowed_namespaces": ["prod"],
    })
    row = await _connector(db, authorized, user_id, cluster="prod-cluster")
    fake = FakeKubernetes()
    run = await _run(db, authorized, user_id, runtime, row, fake)
    assert run.state == "completed" and run.report["created"] == 1
    assert fake.seen == [("prod.example.test", "/apis/apps/v1/namespaces/prod/deployments",
                          f"Bearer {NAMED_TOKEN}")]
    with pytest.raises(ConnectorError) as refused:
        await _connector(db, authorized, user_id, cluster="prod-cluster", namespaces=["shop-test"])
    assert refused.value.reason == "scope_not_allowed"


async def test_a_kubeconfig_only_entry_is_no_connection_and_the_service_account_is_never_used(db, monkeypatch, tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("pod-service-account-token")
    monkeypatch.setattr("app.tools.kubernetes._SA_TOKEN_PATH", token_file)
    authorized, user_id, runtime = await _workspace(db, config={"kubeconfig_path": "/tmp/kubeconfig",
                                                                 "k8s_context": "nonprod"})
    with pytest.raises(ConnectorError) as refused:
        await _connector(db, authorized, user_id, cluster="nonprod")
    assert refused.value.reason in ("connection_not_configured", "own_connection_incomplete")


async def test_the_operations_layer_builds_the_inventory_from_the_connector_kind(db):
    authorized, user_id, runtime = await _workspace(db)
    row = await _connector(db, authorized, user_id, cluster="nonprod")
    await _run(db, authorized, user_id, runtime, row, FakeKubernetes())
    while await EvidenceProjector(runtime).project_once(db, worker_id="test") is not None:
        pass
    assert sync_layers(structured_profile(), "kubernetes") == ["operations"]
    build = await request_build(db, project_id=authorized.project_id, layers=["operations"], trigger=TRIGGER_MANUAL)
    await claim_next_build(db, worker_id="w")
    assert await run_build_slice(db, runtime=runtime, build_id=build.id, worker_id="w") == "completed"
    await db.refresh(build)
    assert build.report["layers"]["operations"]["extracted"] == 2
    assert not build.report["layers"]["operations"]["warnings"]
    deployment = node_id("Deployment", "k8s-deployment:nonprod/shop-test/orders-data-deployment")
    image = node_id("Version", "image:baseimage:3.2-3")
    edges = set((await db.execute(select(KnowledgeStructuredEdge.edge_type).where(
        KnowledgeStructuredEdge.source_id == deployment))).scalars())
    assert edges == {"runs_in", "uses_image"}
    assert (await db.execute(select(KnowledgeStructuredNode.label).where(
        KnowledgeStructuredNode.node_id == image))).scalars().first() == "baseimage:3.2-3"


def test_a_rendered_inventory_names_its_cluster_whole_in_the_graph():
    from app.services.knowledge.structured.facts import SpanRef
    from app.services.knowledge.structured.ops_records import extract_inventory

    cluster = "arn:aws:eks:eu-central-1:1:cluster/shop"
    text = k8s.render_inventory(cluster, "shop-test", [k8s.deployment_of(_deployment("a-deployment", "img/a:1"))],
                                truncated=False).decode()
    extraction = extract_inventory(text, lambda offset: SpanRef(1), structured_profile())
    names = {ref.node_type: node.label for ref, node in extraction.nodes.items()}
    assert names["Cluster"] == cluster and names["Namespace"] == "shop-test" and not extraction.warnings


async def _listed(connection, fake, **kwargs):
    connector = k8s.KubernetesConnector(connection, cluster="c", transport=httpx.MockTransport(fake.handler), **kwargs)
    page = await connector.list_items(None, limit=50)
    return [item.external_id for item in page.items]


async def test_the_connector_reads_only_allowed_namespaces_and_skips_a_gone_one():
    from app.services.knowledge.sources.sync.kubernetes_connection import KubernetesConnection

    fake = FakeKubernetes()
    limited = KubernetesConnection(API, TOKEN, True, frozenset({"shop-test"}))
    assert await _listed(limited, fake, namespaces=("shop-test", "prod")) == ["shop-test"]
    assert {path for _, path, _ in fake.seen} == {"/apis/apps/v1/namespaces/shop-test/deployments"}
    everything = KubernetesConnection(API, TOKEN)
    assert await _listed(everything, fake, namespaces=("gone", "shop-test")) == ["shop-test"]


async def test_the_connection_tls_setting_reaches_the_egress_transport(monkeypatch):
    from app.services.knowledge.sources.sync import http as sync_http
    from app.services.knowledge.sources.sync.kubernetes_connection import KubernetesConnection

    seen: list[bool] = []
    real = sync_http.source_egress_transport

    def spy(kind, *, inner=None, verify=True):
        seen.append(verify)
        return real(kind, inner=inner, verify=verify)

    monkeypatch.setattr(sync_http, "source_egress_transport", spy)
    await _listed(KubernetesConnection(API, TOKEN, False), FakeKubernetes(), namespaces=("shop-test",))
    await _listed(KubernetesConnection(API, TOKEN, True), FakeKubernetes(), namespaces=("shop-test",))
    assert seen == [False, True]


def test_a_url_without_a_token_is_no_connection_even_with_a_pod_service_account(monkeypatch, tmp_path):
    from app.services.knowledge.sources.sync.kubernetes_connection import kubernetes_connection

    token_file = tmp_path / "token"
    token_file.write_text("pod-service-account-token")
    monkeypatch.setattr("app.tools.kubernetes._SA_TOKEN_PATH", token_file)
    assert kubernetes_connection({"k8s_api_url": API}) is None
    assert kubernetes_connection({"k8s_token": TOKEN}) is None
    connection = kubernetes_connection({"k8s_api_url": API + "/", "k8s_token": TOKEN,
                                        "k8s_allowed_namespaces": "a, b", "k8s_verify_tls": False})
    assert connection.base_url == API and connection.allowed_namespaces == {"a", "b"} and connection.verify is False
    assert TOKEN not in repr(connection)
