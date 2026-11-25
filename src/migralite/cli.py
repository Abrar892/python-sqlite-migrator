"""Command-line interface for MigraLite."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .discovery import discover, find_gaps
from .errors import MigrationError
from .runner import connect, migrate_down, migrate_up, validate
from .store import list_applied, table_exists

DEFAULT_DIR = "migrations"
DEFAULT_DB = "app.db"

EXAMPLE_MIGRATION = """-- Example migration: creates a users table.
-- Everything above the `-- @down` marker runs on `migrate up`;
-- everything below it runs on `migrate down`.

CREATE TABLE users (
    id         INTEGER PRIMARY KEY,
    email      TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- @down

DROP TABLE users;
"""

NEW_TEMPLATE = """-- {label}: describe what this migration does here.

-- Write the forward change below this line.

-- @down

-- Write the rollback below this line.
-- Leave the down section empty and the migration is irreversible.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="migralite",
        description="Zero-dependency SQLite database migration runner.",
    )
    parser.add_argument("--db", default=DEFAULT_DB,
                        help="SQLite database file (default: app.db)")
    parser.add_argument("--dir", default=DEFAULT_DIR,
                        help="Migrations directory (default: migrations)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init",
                   help="Create a migrations directory with an example migration.")
    new_p = sub.add_parser("new", help="Create a new empty migration file.")
    new_p.add_argument("description",
                       help="Short snake_case description, e.g. add_users_table")

    up_p = sub.add_parser("up", help="Apply pending migrations.")
    up_p.add_argument("--to", type=int,
                      help="Apply only up to this version.")
    up_p.add_argument("--dry-run", action="store_true",
                      help="Show what would run, without touching the database.")

    down_p = sub.add_parser("down", help="Roll back applied migrations.")
    down_p.add_argument("--to", type=int,
                        help="Roll back everything above this version.")
    down_p.add_argument("--steps", type=int, default=1,
                        help="How many migrations to roll back (default: 1).")

    sub.add_parser("status", help="Show applied and pending migrations.")
    sub.add_parser("validate",
                   help="Check migration files and checksums without changing anything.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = Path(args.db)
    directory = Path(args.dir)
    try:
        if args.command == "init":
            return cmd_init(directory)
        if args.command == "new":
            return cmd_new(directory, args.description)
        if args.command == "up":
            return cmd_up(db_path, directory, args.to, args.dry_run)
        if args.command == "down":
            return cmd_down(db_path, directory, args.to, args.steps)
        if args.command == "status":
            return cmd_status(db_path, directory)
        if args.command == "validate":
            return cmd_validate(db_path, directory)
    except MigrationError as exc:
        print(f"migralite: error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_init(directory: Path) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    example = directory / "V001__create_example_table.sql"
    if example.exists():
        print(f"init: {example} already exists, leaving it alone.")
        return 0
    example.write_text(EXAMPLE_MIGRATION, encoding="utf-8")
    print(f"init: created {directory}/ with example migration V001__create_example_table.sql")
    return 0


def cmd_new(directory: Path, description: str) -> int:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", description):
        print("migralite: error: description must be snake_case, e.g. add_users_table",
              file=sys.stderr)
        return 2
    migrations = discover(directory)
    next_version = (migrations[-1].version + 1) if migrations else 1
    filename = f"V{next_version:03d}__{description}.sql"
    path = directory / filename
    path.write_text(NEW_TEMPLATE.format(label=filename[:-4]), encoding="utf-8")
    print(f"new: created {path}")
    return 0


def cmd_up(db_path: Path, directory: Path, target, dry_run: bool) -> int:
    applied = migrate_up(db_path, directory, target=target, dry_run=dry_run)
    if not applied:
        print("up: database is already up to date.")
        return 0
    for mig in applied:
        verb = "would apply" if dry_run else "applied"
        print(f"up: {verb} {mig.label}")
    if dry_run:
        print(f"up: dry run — {len(applied)} migration(s) pending, nothing changed.")
    return 0


def cmd_down(db_path: Path, directory: Path, target, steps: int) -> int:
    rolled_back = migrate_down(db_path, directory, target=target, steps=steps)
    if not rolled_back:
        print("down: nothing to roll back.")
        return 0
    for mig in rolled_back:
        print(f"down: rolled back {mig.label}")
    return 0


def cmd_status(db_path: Path, directory: Path) -> int:
    migrations = discover(directory)
    applied: dict[int, str] = {}
    if db_path.exists():
        with connect(db_path) as conn:
            if table_exists(conn):
                applied = {a.version: a.applied_at for a in list_applied(conn)}
    for mig in migrations:
        state = f"applied {applied[mig.version]}" if mig.version in applied else "pending"
        print(f"{mig.label:<40} {state}")
    for gap in find_gaps(migrations):
        print(f"warning: missing migration version V{gap:03d} (gap in sequence)")
    if not migrations:
        print("status: no migrations found.")
    return 0


def cmd_validate(db_path: Path, directory: Path) -> int:
    problems = validate(db_path, directory)
    if not problems:
        print("validate: OK — files and checksums are consistent.")
        return 0
    for problem in problems:
        print(f"validate: {problem}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
