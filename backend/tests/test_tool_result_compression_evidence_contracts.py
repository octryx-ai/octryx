"""Evidence contracts for AWS security posture, config and incident bundle results and database queries."""

import uuid

import pytest
from sqlalchemy import select

from app.agent.loops.outcome._loop_evidence_contracts import (
    build_incomplete_evidence_contract_reminder,
    critical_incomplete_evidence_contracts,
)
from app.models import Session, User
from app.services.tool_result_compression import compress_tool_result_for_model


@pytest.mark.asyncio
async def test_aws_security_posture_tool_result_gets_evidence_contract(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    compressed = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="aws_security_posture_summary",
        result={
            "status": "ok",
            "topology_source": "provided",
            "account_id": "123456789012",
            "region": "eu-central-1",
            "summary": {"finding_count": 1, "by_severity": {"high": 1}, "has_critical": False},
            "findings": [
                {
                    "category": "public_ingress",
                    "severity": "high",
                    "title": "Public ingress allowed to api",
                    "evidence": {"edge": [{"service": "ec2", "operation": "describe-security-groups"}]},
                }
            ],
            "warnings": [],
        },
    )

    contract = compressed["evidence_contract"]
    assert contract["status"] == "passed"
    assert contract["tool_name"] == "aws_security_posture_summary"
    assert contract["missing_paths"] == []


@pytest.mark.asyncio
async def test_aws_config_query_blocked_result_gets_non_missing_evidence_contract(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    compressed = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="aws_config_query",
        result={
            "status": "blocked",
            "service": "configservice",
            "error": "AWS service 'configservice' is not allowed by project policy",
            "items": [],
            "warnings": [
                {
                    "service": "configservice",
                    "operation": "select-resource-config",
                    "severity": "warning",
                    "message": "not allowed",
                }
            ],
        },
    )

    contract = compressed["evidence_contract"]
    assert contract["status"] == "passed"
    assert contract["required_paths"] == ["status", "error", "warnings"]
    assert contract["missing_paths"] == []


@pytest.mark.asyncio
async def test_aws_incident_bundle_hard_cap_is_critical_incomplete_evidence(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    compressed = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="aws_incident_evidence_bundle",
        result={
            "status": "ok",
            "incident": {"id": "INC-1", "title": "AWS incident", "severity": "high"},
            "summary": {"section_count": 1, "evidence_reference_count": 100, "redaction_count": 0},
            "sections": [
                {
                    "name": "additional_evidence",
                    "item_count": 100,
                    "payload": [{"resource": f"resource-{index}", "details": "x" * 2000} for index in range(100)],
                }
            ],
            "redactions": [],
            "warnings": [{"severity": "warning", "message": "bundle only"}],
        },
    )

    contract = compressed["evidence_contract"]
    assert contract["status"] == "failed"
    assert contract["hard_capped"] is True
    incomplete = critical_incomplete_evidence_contracts(
        [
            {
                "artifact_id": "artifact-aws-1",
                "tool_name": "aws_incident_evidence_bundle",
                "compact_result": compressed,
            }
        ]
    )
    assert incomplete == [
        {
            "artifact_id": "artifact-aws-1",
            "tool_name": "aws_incident_evidence_bundle",
            "missing_paths": contract["missing_paths"],
            "hard_capped": True,
            "evidence_state": "incomplete_compact_evidence",
        }
    ]
    assert "AWS intelligence" in build_incomplete_evidence_contract_reminder(incomplete)


@pytest.mark.asyncio
async def test_database_query_tool_result_gets_evidence_contract_and_allows_empty_rows(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    result = {
        "tool_name": "database_tool_shop_tables",
        "connector_name": "support-shop-readonly",
        "db_type": "postgresql",
        "row_count": 0,
        "max_rows": 100,
        "rows": [],
        "applied_rls_rules": [],
    }

    compressed = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="database_tool_shop_tables",
        result=result,
    )

    contract = compressed["evidence_contract"]
    assert contract["status"] == "passed"
    assert contract["tool_name"] == "database_tool_shop_tables"
    assert contract["strategy"] == "fallback"
    assert contract["missing_paths"] == []
    assert contract["required_paths"] == [
        "tool_name",
        "connector_name",
        "db_type",
        "row_count",
        "max_rows",
        "rows",
        "applied_rls_rules",
    ]


@pytest.mark.asyncio
async def test_database_query_tool_evidence_contract_marks_missing_and_hard_capped_results_incomplete(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    missing_rows = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="database_tool_shop_schema",
        result={
            "tool_name": "database_tool_shop_schema",
            "connector_name": "support-shop-readonly",
            "db_type": "postgresql",
            "row_count": 4,
            "max_rows": 100,
            "applied_rls_rules": [],
        },
    )

    assert missing_rows["evidence_contract"]["status"] == "failed"
    assert missing_rows["evidence_contract"]["missing_paths"] == ["rows"]

    hard_capped = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="database_tool_shop_schema",
        result={
            "tool_name": "database_tool_shop_schema",
            "connector_name": "support-shop-readonly",
            "db_type": "postgresql",
            "row_count": 80,
            "max_rows": 100,
            "rows": [{"table_name": f"trx_partition_{index}", "ddl": "x" * 2000} for index in range(80)],
            "applied_rls_rules": [],
        },
    )

    contract = hard_capped["evidence_contract"]
    assert contract["status"] == "failed"
    assert contract["hard_capped"] is True
    incomplete = critical_incomplete_evidence_contracts(
        [
            {
                "artifact_id": "artifact-db-1",
                "tool_name": "database_tool_shop_schema",
                "compact_result": hard_capped,
            }
        ]
    )
    assert incomplete == [
        {
            "artifact_id": "artifact-db-1",
            "tool_name": "database_tool_shop_schema",
            "missing_paths": contract["missing_paths"],
            "hard_capped": True,
            "evidence_state": "incomplete_compact_evidence",
        }
    ]
    assert "database schema" in build_incomplete_evidence_contract_reminder(incomplete)
