from pathlib import Path
from xml.etree import ElementTree

import pytest

from app.tools.context import ToolContext
from app.tools.diagram import CreateDiagramTool
from app.tools.registry import TOOL_REGISTRY, execute_tool


@pytest.mark.asyncio
async def test_get_shape_library_tool_returns_aws4_documentation(tmp_path: Path):
    context = ToolContext(
        user_id="test-user",
        project_ids=[],
        roles=["developer"],
        session_id="session-1",
        project_config={},
        workspace_root=str(tmp_path),
        db=None,
    )

    result = await execute_tool("get_shape_library", {"library": "aws4"}, context)

    assert result["library"] == "aws4"
    assert "shape=mxgraph.aws4.resourceIcon" in result["content"]
    assert "dynamodb" in result["content"]
    assert "eks" in result["content"]
    assert "sqs" in result["content"]
    assert "codepipeline" in result["content"]
    assert "aws4" in result["available_libraries"]
    assert "kubernetes" in result["available_libraries"]
    assert len(result["available_libraries"]) >= 25


@pytest.mark.asyncio
async def test_get_shape_library_tool_matches_requested_shapes(tmp_path: Path):
    context = ToolContext(
        user_id="test-user",
        project_ids=[],
        roles=["developer"],
        session_id="session-3",
        project_config={},
        workspace_root=str(tmp_path),
        db=None,
    )

    result = await execute_tool(
        "get_shape_library",
        {"library": "aws4", "shape_names": ["eks", "sqs", "dynamodb", "codepipeline", "terraform"]},
        context,
    )

    matched = {item["requested"]: item["shape"] for item in result["matched_shapes"]}
    assert matched["eks"] == "eks"
    assert matched["sqs"] == "sqs"
    assert matched["dynamodb"] == "dynamodb"
    assert matched["codepipeline"] == "codepipeline"
    assert "terraform" in result["missing_shape_names"]


@pytest.mark.asyncio
async def test_get_shape_library_tool_matches_kubernetes_aliases(tmp_path: Path):
    context = ToolContext(
        user_id="test-user",
        project_ids=[],
        roles=["developer"],
        session_id="session-4",
        project_config={},
        workspace_root=str(tmp_path),
        db=None,
    )

    result = await execute_tool(
        "get_shape_library",
        {"library": "kubernetes", "shape_names": ["ingress", "service", "deployment", "pod"]},
        context,
    )

    matched = {item["requested"]: item["shape"] for item in result["matched_shapes"]}
    assert matched["ingress"] == "ing"
    assert matched["service"] == "svc"
    assert matched["deployment"] == "deploy"
    assert matched["pod"] == "pod"


@pytest.mark.asyncio
async def test_get_shape_library_tool_matches_azure_aliases(tmp_path: Path):
    context = ToolContext(
        user_id="test-user",
        project_ids=[],
        roles=["developer"],
        session_id="session-5",
        project_config={},
        workspace_root=str(tmp_path),
        db=None,
    )

    result = await execute_tool(
        "get_shape_library",
        {"library": "azure2", "shape_names": ["aks", "service_bus", "cosmos_db", "key_vault", "app_gateway"]},
        context,
    )

    matched = {item["requested"]: item["shape"] for item in result["matched_shapes"]}
    assert matched["aks"] == "Kubernetes_Services"
    assert matched["service_bus"] == "Service_Bus"
    assert matched["cosmos_db"] == "Azure_Cosmos_DB"
    assert matched["key_vault"] == "Key_Vaults"
    assert matched["app_gateway"] == "Application_Gateways"


@pytest.mark.asyncio
async def test_get_shape_library_tool_matches_gcp_aliases(tmp_path: Path):
    context = ToolContext(
        user_id="test-user",
        project_ids=[],
        roles=["developer"],
        session_id="session-6",
        project_config={},
        workspace_root=str(tmp_path),
        db=None,
    )

    result = await execute_tool(
        "get_shape_library",
        {"library": "gcp2", "shape_names": ["cloud_run", "pubsub", "bigquery", "cloud_sql", "compute_engine"]},
        context,
    )

    matched = {item["requested"]: item["shape"] for item in result["matched_shapes"]}
    assert matched["cloud_run"] == "cloud_run"
    assert matched["pubsub"] == "cloud_pubsub"
    assert matched["bigquery"] == "bigquery"
    assert matched["cloud_sql"] == "cloud_sql"
    assert matched["compute_engine"] == "compute_engine"


@pytest.mark.asyncio
async def test_get_shape_library_tool_rejects_invalid_library_name(tmp_path: Path):
    context = ToolContext(
        user_id="test-user",
        project_ids=[],
        roles=["developer"],
        session_id="session-2",
        project_config={},
        workspace_root=str(tmp_path),
        db=None,
    )

    result = await execute_tool("get_shape_library", {"library": "../aws4"}, context)

    assert "Invalid library name" in result["error"]
    assert "aws4" in result["available_libraries"]


def test_tool_registry_exposes_shape_library_tool():
    assert "get_shape_library" in TOOL_REGISTRY


@pytest.mark.asyncio
async def test_create_diagram_normalizes_visible_parent_zero_to_layer_one():
    tool = CreateDiagramTool()

    result = await tool.execute(
        {
            "title": "AWS topology",
            "xml": (
                '<mxCell id="vpc" value="vpc-1" style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.vpc;" '
                'vertex="1" parent="0"><mxGeometry x="80" y="80" width="60" height="60" as="geometry"/></mxCell>'
                '<mxCell id="alb" value="alb-1" style="shape=mxgraph.aws4.resourceIcon;'
                'resIcon=mxgraph.aws4.application_load_balancer;" vertex="1" parent="0">'
                '<mxGeometry x="200" y="80" width="60" height="60" as="geometry"/></mxCell>'
                '<mxCell id="e1" edge="1" source="alb" target="vpc" parent="0">'
                '<mxGeometry relative="1" as="geometry"/></mxCell>'
            ),
        },
        None,  # type: ignore[arg-type]
    )

    assert result["status"] == "created"
    assert "Normalized visible mxCell parent=0 to parent=1" in result["auto_fixes_applied"]

    root = ElementTree.fromstring(result["diagram_xml"])
    cells = {cell.attrib.get("id"): cell.attrib for cell in root.findall("./root/mxCell")}

    assert cells["0"] == {"id": "0"}
    assert cells["1"] == {"id": "1", "parent": "0"}
    assert cells["vpc"]["parent"] == "1"
    assert cells["alb"]["parent"] == "1"
    assert cells["e1"]["parent"] == "1"


@pytest.mark.asyncio
async def test_create_diagram_repairs_llm_id_written_into_vertex_attr():
    tool = CreateDiagramTool()

    result = await tool.execute(
        {
            "title": "AWS topology",
            "xml": (
                '<mxCell value="WAF" style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.waf;" '
                'vertex="waf_1" parent="1"><mxGeometry x="100" y="100" width="60" height="60" '
                'as="geometry"/></mxCell>'
                '<mxCell value="Private Subnet" style="shape=mxgraph.aws4.resourceIcon;'
                'resC=mxgraph.aws4.group_subnet;" vertex="priv_sub_1" parent="1">'
                '<mxGeometry x="250" y="350" width="300" height="150" as="geometry"/></mxCell>'
                '<mxCell edge="1" source="waf_1" target="priv_sub_1">'
                '<mxGeometry relative="1" as="geometry"/></mxCell>'
            ),
        },
        None,  # type: ignore[arg-type]
    )

    assert result["status"] == "created"
    assert "Moved non-boolean vertex values into mxCell id attributes" in result["auto_fixes_applied"]
    assert "Added missing mxCell id attributes" in result["auto_fixes_applied"]
    assert "Added missing visible mxCell parent attributes" in result["auto_fixes_applied"]
    assert "Fixed AWS style typo resC= \u2192 resIcon=" in result["auto_fixes_applied"]

    root = ElementTree.fromstring(result["diagram_xml"])
    cells = {cell.attrib.get("id"): cell.attrib for cell in root.findall("./root/mxCell")}

    assert cells["waf_1"]["vertex"] == "1"
    assert cells["priv_sub_1"]["vertex"] == "1"
    assert "resIcon=mxgraph.aws4.group_subnet" in cells["priv_sub_1"]["style"]
    generated_edges = [attrs for cell_id, attrs in cells.items() if str(cell_id).startswith("edge_auto_")]
    assert generated_edges
    assert generated_edges[0]["parent"] == "1"
