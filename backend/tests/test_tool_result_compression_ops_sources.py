"""Compressing kubectl pod lists and Grafana, Jira and Loki results."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Session, ToolResultCompressionLog, User
from app.services.tool_result_compression import compress_tool_result_for_model


@pytest.mark.asyncio
async def test_run_kubectl_pod_list_is_compressed_to_failed_pods_and_logged(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    result = {
        "command": ["kubectl", "-n", "acme-orders", "get", "pods", "-o", "json"],
        "exit_code": 0,
        "stdout": """
        {
          "items": [
            {
              "metadata": {"name": "api-1", "namespace": "acme-orders"},
              "status": {
                "phase": "Running",
                "containerStatuses": [{"name": "api", "restartCount": 0, "state": {"running": {}}}]
              }
            },
            {
              "metadata": {"name": "api-2", "namespace": "acme-orders"},
              "status": {
                "phase": "Running",
                "containerStatuses": [
                  {"name": "api", "restartCount": 7, "state": {"waiting": {"reason": "CrashLoopBackOff"}}}
                ]
              }
            },
            {
              "metadata": {"name": "worker-1", "namespace": "acme-orders"},
              "status": {
                "phase": "Failed",
                "containerStatuses": [
                  {"name": "worker", "restartCount": 2, "state": {"terminated": {"reason": "OOMKilled"}}}
                ]
              }
            }
          ]
        }
        """,
        "stderr": "",
    }

    compressed = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="run_kubectl",
        result=result,
    )
    assert compressed["failed_count"] == 2
    assert len(compressed["failed_pods"]) == 2
    assert {item["pod"] for item in compressed["failed_pods"]} == {"api-2", "worker-1"}

    log = (
        await db.execute(
            select(ToolResultCompressionLog).where(
                ToolResultCompressionLog.session_id == session.id,
                ToolResultCompressionLog.tool_name == "run_kubectl",
            )
        )
    ).scalar_one()
    assert log.strategy == "k8s_pod_failures"
    assert log.compressed_tokens < log.original_tokens


@pytest.mark.asyncio
async def test_grafana_jira_and_loki_results_are_compressed(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    grafana = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="list_grafana_alerts",
        result={
            "total_rules": 5,
            "active": [
                {
                    "labels": {"alertname": "CPUHigh", "severity": "critical", "service": "api"},
                    "annotations": {"summary": "CPU is too high"},
                    "status": {"state": "firing"},
                    "startsAt": "2026-01-01T00:00:00Z",
                },
                {
                    "labels": {"alertname": "Info", "service": "api"},
                    "annotations": {"summary": "Recovered"},
                    "status": {"state": "normal"},
                    "startsAt": "2026-01-01T00:00:00Z",
                },
            ],
        },
    )
    assert grafana["firing_alert_count"] == 1
    assert grafana["alerts"][0]["alertname"] == "CPUHigh"

    jira = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="search_jira_tickets",
        result={
            "query": "payment",
            "results": [
                {
                    "id": "100",
                    "key": "RIVER-1",
                    "summary": "Payment timeout",
                    "status": {"name": "In Progress"},
                    "assignee": {"displayName": "Alice"},
                    "reporter": {"displayName": "Bob"},
                    "creator": {"displayName": "Alice"},
                    "priority": {"name": "High"},
                    "issuetype": {"name": "Task"},
                    "created": "2026-01-02T09:00:00.000+0100",
                    "updated": "2026-01-03T10:00:00.000+0100",
                },
            ],
        },
    )
    assert jira["results"] == [
        {
            "id": "100",
            "ticket_id": "RIVER-1",
            "key": "RIVER-1",
            "summary": "Payment timeout",
            "status": "In Progress",
            "assignee": "Alice",
            "reporter": "Bob",
            "creator": "Alice",
            "priority": "High",
            "issue_type": "Task",
            "created": "2026-01-02T09:00:00.000+0100",
            "updated": "2026-01-03T10:00:00.000+0100",
        }
    ]
    assert jira["status_counts"] == {"In Progress": 1}
    assert jira["issue_type_counts"] == {"Task": 1}
    assert jira["top_assignees"] == {"Alice": 1}

    loki = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="query_loki",
        result={
            "query": '{app="api"}',
            "total_lines": 3,
            "streams_count": 1,
            "streams": [
                {
                    "stream": {"app": "api"},
                    "values": [
                        ["1", "INFO boot"],
                        ["2", "ERROR payment failed"],
                        ["3", "Traceback stack"],
                    ],
                }
            ],
        },
    )
    assert len(loki["tail_lines"]) == 3
    assert len(loki["error_lines"]) == 2
