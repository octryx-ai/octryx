from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def utc_now_aware() -> datetime:
    return datetime.now(UTC)


def ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def utc_isoformat(dt: datetime | None) -> str | None:
    normalized = ensure_utc(dt)
    if normalized is None:
        return None
    return normalized.isoformat().replace("+00:00", "Z")
