"""Seeding default tool result compressors, kept edited configs, governed overrides and supported strategies."""

import json
import uuid

import pytest
from sqlalchemy import select

from app.models import Session, ToolResultCompressor, User
from app.services.system_config.values import set_system_config_value
from app.services.tool_result_compression import (
    DEFAULT_COMPRESSORS,
    compress_tool_result_for_model,
    ensure_default_tool_result_compressors,
)
from app.services.tool_result_compression.governance import DEFAULT_COMPRESSOR_GOVERNANCE_CONFIG_KEY
from app.services.tool_result_compression.registry import STRATEGY_HANDLERS
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
async def test_default_tool_result_compressors_are_seeded(db):
    await ensure_default_tool_result_compressors(db)
    rows = (await db.execute(select(ToolResultCompressor))).scalars().all()
    names = {row.tool_name for row in rows}
    assert set(DEFAULT_COMPRESSORS).issubset(names)


@pytest.mark.asyncio
async def test_default_tool_result_compressors_keep_edited_configs(db):
    await ensure_default_tool_result_compressors(db)
    jira = (
        await db.execute(select(ToolResultCompressor).where(ToolResultCompressor.tool_name == "search_jira_tickets"))
    ).scalar_one()
    jira.config = {"max_items": 50}
    await db.commit()

    await ensure_default_tool_result_compressors(db)

    assert jira.config == {"max_items": 50}


@pytest.mark.asyncio
async def test_default_tool_result_compressors_can_use_governed_overrides(db):
    await set_system_config_value(
        db,
        key=DEFAULT_COMPRESSOR_GOVERNANCE_CONFIG_KEY,
        value=json.dumps({"run_kubectl": {"config": {"max_items": 7}}}),
    )

    seeded_row = (
        await db.execute(select(ToolResultCompressor).where(ToolResultCompressor.tool_name == "run_kubectl"))
    ).scalar_one()
    await db.delete(seeded_row)
    await db.flush()

    await ensure_default_tool_result_compressors(db)
    run_kubectl = (
        await db.execute(select(ToolResultCompressor).where(ToolResultCompressor.tool_name == "run_kubectl"))
    ).scalar_one()

    assert run_kubectl.strategy == "k8s_pod_failures"
    assert run_kubectl.config["max_items"] == 7
    rows = (await db.execute(select(ToolResultCompressor))).scalars().all()
    names = {row.tool_name for row in rows}
    assert set(DEFAULT_COMPRESSORS).issubset(names)


@pytest.mark.asyncio
async def test_tool_result_compression_uses_governed_seed_when_row_is_missing(db):
    await set_system_config_value(
        db,
        key=DEFAULT_COMPRESSOR_GOVERNANCE_CONFIG_KEY,
        value=json.dumps({"run_kubectl": {"config": {"max_items": 7}}}),
    )
    await ensure_default_tool_result_compressors(db)
    row = (
        await db.execute(select(ToolResultCompressor).where(ToolResultCompressor.tool_name == "run_kubectl"))
    ).scalar_one()
    await db.delete(row)
    await db.flush()

    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    result = {
        "command": ["kubectl", "-n", "acme-orders", "get", "pods", "-o", "json"],
        "exit_code": 0,
        "stdout": json.dumps(
            {
                "items": [
                    {
                        "metadata": {"name": f"api-{i}", "namespace": "acme-orders"},
                        "status": {
                            "phase": "Failed",
                            "containerStatuses": [
                                {
                                    "name": "api",
                                    "restartCount": i,
                                    "state": {"terminated": {"reason": "OOMKilled"}},
                                }
                            ],
                        },
                    }
                    for i in range(10)
                ]
            }
        ),
        "stderr": "",
    }

    compressed = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="run_kubectl",
        result=result,
    )

    assert compressed["failed_count"] == 10
    assert len(compressed["failed_pods"]) == 7


@pytest.mark.asyncio
async def test_inactive_tool_result_compressor_still_blocks_governed_seed(db):
    await set_system_config_value(
        db,
        key=DEFAULT_COMPRESSOR_GOVERNANCE_CONFIG_KEY,
        value=json.dumps({"run_kubectl": {"config": {"max_items": 7}}}),
    )
    await ensure_default_tool_result_compressors(db)
    row = (
        await db.execute(select(ToolResultCompressor).where(ToolResultCompressor.tool_name == "run_kubectl"))
    ).scalar_one()
    row.is_active = False
    await db.flush()

    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    result = {
        "command": ["kubectl", "-n", "acme-orders", "get", "pods", "-o", "json"],
        "exit_code": 0,
        "stdout": json.dumps({"items": []}),
        "stderr": "",
    }

    compressed = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="run_kubectl",
        result=result,
    )

    assert compressed == result


@pytest.mark.asyncio
async def test_tool_result_compressor_admin_api_uses_governed_seed_when_reseeded(client, db):
    await set_system_config_value(
        db,
        key=DEFAULT_COMPRESSOR_GOVERNANCE_CONFIG_KEY,
        value=json.dumps({"run_kubectl": {"config": {"max_items": 7}}}),
    )
    seeded_row = (
        await db.execute(select(ToolResultCompressor).where(ToolResultCompressor.tool_name == "run_kubectl"))
    ).scalar_one()
    await db.delete(seeded_row)
    await db.commit()

    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    list_resp = await client.get("/admin/chat/api/panel/tool-result-compressors")
    assert list_resp.status_code == 200
    compressors = list_resp.json()
    run_kubectl = next(item for item in compressors if item["tool_name"] == "run_kubectl")
    assert run_kubectl["strategy"] == "k8s_pod_failures"
    assert run_kubectl["config"]["max_items"] == 7

    update_resp = await client.put(
        "/admin/chat/api/panel/tool-result-compressors/run_kubectl",
        json={"strategy": "k8s_pod_failures", "config": {"max_items": 9}, "is_active": True},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["config"]["max_items"] == 9


def test_default_tool_result_compressors_use_supported_strategies():
    unsupported = {
        tool_name: payload["strategy"]
        for tool_name, payload in DEFAULT_COMPRESSORS.items()
        if payload["strategy"] not in STRATEGY_HANDLERS
    }
    assert unsupported == {}
