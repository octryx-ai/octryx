from __future__ import annotations

from datetime import date

from fastapi import HTTPException


def parse_report_period(period: str) -> tuple[str, date, date]:
    normalized = str(period or "").strip()
    try:
        year_str, month_str = normalized.split("-", 1)
        year = int(year_str)
        month = int(month_str)
        start = date(year, month, 1)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid period. Expected YYYY-MM.") from exc
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return normalized, start, end
