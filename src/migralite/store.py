"""The ``schema_migrations`` bookkeeping table."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    checksum   TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""


@dataclass(frozen=True)
class AppliedMigration:
    version: int
    name: str
    checksum: str
    applied_at: str


def table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    return row is not None


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(TABLE_SQL)


def list_applied(conn: sqlite3.Connection) -> list[AppliedMigration]:
    """Applied migrations, oldest first. Assumes the table exists."""
    rows = conn.execute(
        "SELECT version, name, checksum, applied_at "
        "FROM schema_migrations ORDER BY version"
    ).fetchall()
    return [AppliedMigration(*row) for row in rows]


def record_applied(conn: sqlite3.Connection, migration) -> None:
    conn.execute(
        "INSERT INTO schema_migrations (version, name, checksum) VALUES (?, ?, ?)",
        (migration.version, migration.name, migration.checksum),
    )


def remove_applied(conn: sqlite3.Connection, version: int) -> None:
    conn.execute("DELETE FROM schema_migrations WHERE version = ?", (version,))
