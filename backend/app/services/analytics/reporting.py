from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AnalyticsDaily
from .serialization import serialize_analytics_daily

ALLOWED_REPORT_TYPES = {
    "cost_summary",
    "team_activity",
    "agent_performance",
    "incident_resolution",
    "knowledge_coverage",
}
ALLOWED_REPORT_FORMATS = {"json", "csv", "pdf"}


async def analytics_rows_for_export(db: AsyncSession, *, parameters: dict[str, Any]) -> list[AnalyticsDaily]:
    stmt = select(AnalyticsDaily).order_by(AnalyticsDaily.date.asc())
    project_id = str(parameters.get("project_id") or "").strip()
    team_id = str(parameters.get("team_id") or "").strip()
    date_from = str(parameters.get("date_from") or "").strip()
    date_to = str(parameters.get("date_to") or "").strip()
    if project_id:
        stmt = stmt.where(AnalyticsDaily.project_id == project_id)
    if team_id:
        stmt = stmt.where(AnalyticsDaily.team_id == team_id)
    if date_from:
        stmt = stmt.where(AnalyticsDaily.date >= date.fromisoformat(date_from))
    if date_to:
        stmt = stmt.where(AnalyticsDaily.date <= date.fromisoformat(date_to))
    return (await db.execute(stmt)).scalars().all()


def build_report_payload(report_type: str, rows: list[AnalyticsDaily]) -> dict[str, Any]:
    serialized = [serialize_analytics_daily(row) for row in rows]
    if report_type == "cost_summary":
        total_cost = round(sum(item["total_cost"] for item in serialized), 4)
        by_project: dict[str, float] = defaultdict(float)
        for item in serialized:
            by_project[str(item["project_id"] or "global")] += float(item["total_cost"] or 0.0)
        return {
            "report_type": report_type,
            "rows": serialized,
            "totals": {"total_cost": total_cost, "by_project": dict(by_project)},
        }
    if report_type == "team_activity":
        return {
            "report_type": report_type,
            "rows": serialized,
            "totals": {
                "sessions_total": sum(item["sessions_total"] for item in serialized),
                "approvals_requested": sum(item["approvals_requested"] for item in serialized),
                "approvals_approved": sum(item["approvals_approved"] for item in serialized),
            },
        }
    if report_type == "agent_performance":
        return {
            "report_type": report_type,
            "rows": serialized,
            "totals": {
                "sessions_completed": sum(item["sessions_completed"] for item in serialized),
                "sessions_failed": sum(item["sessions_failed"] for item in serialized),
                "tool_calls_failed": sum(item["tool_calls_failed"] for item in serialized),
            },
        }
    if report_type == "incident_resolution":
        relevant = [item for item in serialized if item["sessions_total"] > 0]
        avg_minutes = (
            round(sum(float(item["avg_session_duration_minutes"] or 0.0) for item in relevant) / len(relevant), 4)
            if relevant
            else 0.0
        )
        return {"report_type": report_type, "rows": serialized, "totals": {"avg_resolution_minutes": avg_minutes}}
    return {
        "report_type": report_type,
        "rows": serialized,
        "totals": {
            "knowledge_queries": sum(item["knowledge_queries"] for item in serialized),
            "knowledge_hits": sum(item["knowledge_hits"] for item in serialized),
        },
    }


def payload_to_csv_bytes(payload: dict[str, Any]) -> bytes:
    rows = payload.get("rows") or []
    buffer = io.StringIO()
    if not rows:
        buffer.write("report_type\n")
        buffer.write(f"{payload.get('report_type', '')}\n")
        return buffer.getvalue().encode("utf-8")
    fieldnames = list(rows[0].keys())
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_to_pdf_bytes(text: str) -> bytes:
    lines = [line[:100] for line in text.splitlines()[:40]] or ["Octryx report export"]
    content_lines = ["BT", "/F1 11 Tf", "50 780 Td", "14 TL"]
    for index, line in enumerate(lines):
        if index > 0:
            content_lines.append("T*")
        content_lines.append(f"({_escape_pdf_text(line)}) Tj")
    content_lines.append("ET")
    content_stream = "\n".join(content_lines).encode()
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj",
        (
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj"
        ),
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj",
        f"5 0 obj << /Length {len(content_stream)} >> stream\n".encode() + content_stream + b"\nendstream endobj",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
        pdf.extend(b"\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode())
    return bytes(pdf)
