from __future__ import annotations

from typing import Any

POSTGRES_DATABASE_TYPES = {"postgres", "postgresql"}
SQLITE_DATABASE_TYPES = {"sqlite"}
SUPPORTED_DATABASE_TYPES = {
    *POSTGRES_DATABASE_TYPES,
    *SQLITE_DATABASE_TYPES,
    "mysql",
    "mariadb",
    "mssql",
    "sqlserver",
}


def normalize_database_type(db_type: Any) -> str:
    return str(db_type or "postgresql").strip().lower()


def database_runtime_profile(db_type: Any) -> dict[str, Any]:
    normalized = normalize_database_type(db_type)
    if normalized in POSTGRES_DATABASE_TYPES:
        return {
            "db_type": normalized,
            "supported": True,
            "enterprise_acceptance": True,
            "acceptance_mode": "production_postgres",
            "sqlite_boundary": "not_sqlite",
            "notes": "PostgreSQL is the enterprise database-tool acceptance baseline.",
        }
    if normalized in SQLITE_DATABASE_TYPES:
        return {
            "db_type": normalized,
            "supported": True,
            "enterprise_acceptance": False,
            "acceptance_mode": "local_fixture_only",
            "sqlite_boundary": "local_or_test_fixture",
            "notes": "SQLite connectors are local/fixture convenience and do not satisfy enterprise acceptance.",
        }
    if normalized in SUPPORTED_DATABASE_TYPES:
        return {
            "db_type": normalized,
            "supported": True,
            "enterprise_acceptance": False,
            "acceptance_mode": "supported_external_connector",
            "sqlite_boundary": "not_sqlite",
            "notes": "Supported connector type, but not the PostgreSQL enterprise acceptance baseline.",
        }
    return {
        "db_type": normalized,
        "supported": False,
        "enterprise_acceptance": False,
        "acceptance_mode": "unsupported",
        "sqlite_boundary": "unknown",
        "notes": "Unsupported database connector type.",
    }


__all__ = [
    "POSTGRES_DATABASE_TYPES",
    "SQLITE_DATABASE_TYPES",
    "SUPPORTED_DATABASE_TYPES",
    "database_runtime_profile",
    "normalize_database_type",
]
