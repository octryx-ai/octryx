"""The external SQLite database fixture shared by the test_database_tool_* modules."""

import sqlite3


def _create_external_sqlite_db(path, *, primary_tenant_id: str, primary_team: str = "ops"):
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            create table orders (
                id integer primary key,
                tenant_id text not null,
                role_name text not null,
                team_name text not null,
                status text not null
            )
            """
        )
        conn.executemany(
            "insert into orders (tenant_id, role_name, team_name, status) values (?, ?, ?, ?)",
            [
                (primary_tenant_id, "admin", primary_team, "open"),
                (primary_tenant_id, "admin", primary_team, "closed"),
                ("someone-else", "member", "sales", "open"),
            ],
        )
        conn.commit()
    finally:
        conn.close()
