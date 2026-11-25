"""Apply and roll back migrations against a SQLite database."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .discovery import discover
from .errors import ChecksumError, IrreversibleError, MigrationError
from .migration import Migration, split_statements
from .store import (
    ensure_table,
    list_applied,
    record_applied,
    remove_applied,
    table_exists,
)


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def check_drift(conn: sqlite3.Connection, migrations: list[Migration]) -> None:
    """Fail if an applied migration's file no longer matches its checksum,
    or if an applied migration's file has gone missing entirely."""
    applied = {a.version: a for a in list_applied(conn)}
    by_version = {m.version: m for m in migrations}
    for version, row in applied.items():
        mig = by_version.get(version)
        if mig is None:
            raise MigrationError(
                f"Applied migration V{version:03d}__{row.name} is missing from the "
                "migrations directory; refusing to continue."
            )
        if mig.checksum != row.checksum:
            raise ChecksumError(
                f"Migration V{version:03d}__{row.name} changed after it was applied "
                "(checksum mismatch). Fix applied migrations only via a new migration."
            )


def pending_migrations(
    migrations: list[Migration], applied_versions: set[int]
) -> list[Migration]:
    return [m for m in migrations if m.version not in applied_versions]


def migrate_up(
    db_path: Path,
    directory: Path,
    target: int | None = None,
    dry_run: bool = False,
) -> list[Migration]:
    """Apply pending migrations in version order; return what was applied.

    With ``dry_run`` nothing is written — not even the bookkeeping table —
    and the migrations that *would* run are returned instead.
    """
    migrations = discover(directory)
    if dry_run:
        applied: set[int] = set()
        if Path(db_path).exists():
            with connect(db_path) as conn:
                if table_exists(conn):
                    check_drift(conn, migrations)
                    applied = {a.version for a in list_applied(conn)}
        pending = pending_migrations(migrations, applied)
        if target is not None:
            pending = [m for m in pending if m.version <= target]
        return pending

    with connect(db_path) as conn:
        ensure_table(conn)
        check_drift(conn, migrations)
        applied = {a.version for a in list_applied(conn)}
        pending = pending_migrations(migrations, applied)
        if target is not None:
            pending = [m for m in pending if m.version <= target]
        for mig in pending:
            _apply(conn, mig)
        return pending


def _apply(conn: sqlite3.Connection, mig: Migration) -> None:
    statements = split_statements(mig.up_sql)
    if not statements:
        raise MigrationError(f"Migration {mig.label} has no up SQL.")
    try:
        conn.execute("BEGIN")
        for stmt in statements:
            conn.execute(stmt)
        record_applied(conn, mig)
        conn.execute("COMMIT")
    except sqlite3.Error as exc:
        conn.execute("ROLLBACK")
        raise MigrationError(f"Migration {mig.label} failed: {exc}") from exc


def migrate_down(
    db_path: Path,
    directory: Path,
    target: int | None = None,
    steps: int = 1,
) -> list[Migration]:
    """Roll back applied migrations, newest first; return what was rolled back.

    ``target`` rolls back everything above that version; otherwise ``steps``
    migrations are rolled back (default 1).
    """
    if target is None and steps < 1:
        raise MigrationError("--steps must be at least 1.")
    migrations = discover(directory)
    by_version = {m.version: m for m in migrations}
    with connect(db_path) as conn:
        ensure_table(conn)
        check_drift(conn, migrations)
        applied = list_applied(conn)
        if not applied:
            return []
        if target is not None:
            to_rollback = [a for a in applied if a.version > target]
        else:
            to_rollback = applied[-steps:]
        rolled_back: list[Migration] = []
        for row in reversed(to_rollback):
            mig = by_version[row.version]
            if not mig.reversible:
                raise IrreversibleError(
                    f"Migration {mig.label} has no down SQL (-- @down section); "
                    "cannot roll it back."
                )
            _rollback(conn, mig)
            rolled_back.append(mig)
        return rolled_back


def _rollback(conn: sqlite3.Connection, mig: Migration) -> None:
    statements = split_statements(mig.down_sql)
    try:
        conn.execute("BEGIN")
        for stmt in statements:
            conn.execute(stmt)
        remove_applied(conn, mig.version)
        conn.execute("COMMIT")
    except sqlite3.Error as exc:
        conn.execute("ROLLBACK")
        raise MigrationError(f"Rollback of {mig.label} failed: {exc}") from exc


def validate(db_path: Path, directory: Path) -> list[str]:
    """Return a list of problems; an empty list means everything checks out."""
    problems: list[str] = []
    try:
        migrations = discover(directory)
    except MigrationError as exc:
        return [str(exc)]
    from .discovery import find_gaps

    for gap in find_gaps(migrations):
        problems.append(f"Missing migration version V{gap:03d} (gap in sequence).")
    if not Path(db_path).exists():
        return problems  # nothing applied yet; file checks are all we have
    with connect(db_path) as conn:
        if table_exists(conn):
            try:
                check_drift(conn, migrations)
            except MigrationError as exc:
                problems.append(str(exc))
    return problems
