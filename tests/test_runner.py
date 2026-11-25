"""Tests for the migration runner: up, down, drift, atomicity."""
import sqlite3
from pathlib import Path

import pytest

from migralite.discovery import discover
from migralite.errors import ChecksumError, IrreversibleError, MigrationError
from migralite.runner import (
    connect,
    migrate_down,
    migrate_up,
    validate,
)
from migralite.store import list_applied


def _write(directory: Path, name: str, content: str) -> None:
    (directory / name).write_text(content, encoding="utf-8")


@pytest.fixture
def migrations(tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    _write(
        directory,
        "V001__create_users.sql",
        "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);\n"
        "\n-- @down\n\nDROP TABLE users;\n",
    )
    _write(
        directory,
        "V002__add_posts.sql",
        "CREATE TABLE posts (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id));\n"
        "INSERT INTO users (id, email) VALUES (1, 'a@example.com');\n"
        "\n-- @down\n\nDROP TABLE posts;\n",
    )
    return directory


def _tables(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {row[0] for row in rows}


def test_up_applies_in_order_and_records(migrations, tmp_path):
    db = tmp_path / "app.db"
    applied = migrate_up(db, migrations)
    assert [m.version for m in applied] == [1, 2]
    assert {"users", "posts", "schema_migrations"} <= _tables(db)
    with connect(db) as conn:
        assert [a.version for a in list_applied(conn)] == [1, 2]


def test_up_is_idempotent(migrations, tmp_path):
    db = tmp_path / "app.db"
    migrate_up(db, migrations)
    assert migrate_up(db, migrations) == []


def test_up_with_target_stops_early(migrations, tmp_path):
    db = tmp_path / "app.db"
    applied = migrate_up(db, migrations, target=1)
    assert [m.version for m in applied] == [1]
    assert "posts" not in _tables(db)


def test_dry_run_changes_nothing(migrations, tmp_path):
    db = tmp_path / "app.db"
    pending = migrate_up(db, migrations, dry_run=True)
    assert [m.version for m in pending] == [1, 2]
    assert not db.exists()


def test_dry_run_after_partial_apply(migrations, tmp_path):
    db = tmp_path / "app.db"
    migrate_up(db, migrations, target=1)
    pending = migrate_up(db, migrations, dry_run=True)
    assert [m.version for m in pending] == [2]
    with connect(db) as conn:
        assert [a.version for a in list_applied(conn)] == [1]


def test_down_rolls_back_newest_first(migrations, tmp_path):
    db = tmp_path / "app.db"
    migrate_up(db, migrations)
    rolled_back = migrate_down(db, migrations, steps=1)
    assert [m.version for m in rolled_back] == [2]
    assert "posts" not in _tables(db)
    assert "users" in _tables(db)
    with connect(db) as conn:
        assert [a.version for a in list_applied(conn)] == [1]


def test_down_to_version(migrations, tmp_path):
    db = tmp_path / "app.db"
    migrate_up(db, migrations)
    rolled_back = migrate_down(db, migrations, target=0)
    assert [m.version for m in rolled_back] == [2, 1]
    assert "users" not in _tables(db)


def test_down_nothing_applied(migrations, tmp_path):
    db = tmp_path / "app.db"
    assert migrate_down(db, migrations) == []


def test_down_irreversible_migration_fails(migrations, tmp_path):
    _write(
        migrations,
        "V003__irreversible.sql",
        "CREATE TABLE logs (id INTEGER PRIMARY KEY);\n",
    )
    db = tmp_path / "app.db"
    migrate_up(db, migrations)
    with pytest.raises(IrreversibleError, match="no down SQL"):
        migrate_down(db, migrations, steps=1)
    # V003 is still applied; nothing was half-rolled-back.
    with connect(db) as conn:
        assert [a.version for a in list_applied(conn)] == [1, 2, 3]


def test_checksum_drift_blocks_up(migrations, tmp_path):
    db = tmp_path / "app.db"
    migrate_up(db, migrations)
    _write(
        migrations,
        "V001__create_users.sql",
        "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, name TEXT);\n"
        "\n-- @down\n\nDROP TABLE users;\n",
    )
    with pytest.raises(ChecksumError, match="changed after it was applied"):
        migrate_up(db, migrations)


def test_missing_applied_file_blocks_up(migrations, tmp_path):
    db = tmp_path / "app.db"
    migrate_up(db, migrations)
    (migrations / "V002__add_posts.sql").unlink()
    with pytest.raises(MigrationError, match="missing from the migrations directory"):
        migrate_up(db, migrations)


def test_failed_migration_rolls_back_atomically(migrations, tmp_path):
    _write(
        migrations,
        "V003__broken.sql",
        "CREATE TABLE broken (id INTEGER PRIMARY KEY);\n"
        "THIS IS NOT SQL;\n"
        "\n-- @down\n\nDROP TABLE broken;\n",
    )
    db = tmp_path / "app.db"
    with pytest.raises(MigrationError, match="V003__broken failed"):
        migrate_up(db, migrations)
    assert "broken" not in _tables(db)
    with connect(db) as conn:
        # V001/V002 were applied in their own transactions; V003 recorded nothing.
        assert [a.version for a in list_applied(conn)] == [1, 2]


def test_validate_ok_and_gap(migrations, tmp_path):
    db = tmp_path / "app.db"
    migrate_up(db, migrations)
    assert validate(db, migrations) == []
    _write(
        migrations,
        "V004__later.sql",
        "CREATE TABLE later (id INTEGER PRIMARY KEY);\n\n-- @down\n\nDROP TABLE later;\n",
    )
    problems = validate(db, migrations)
    assert any("V003" in p and "gap" in p for p in problems)


def test_validate_detects_drift(migrations, tmp_path):
    db = tmp_path / "app.db"
    migrate_up(db, migrations)
    _write(
        migrations,
        "V002__add_posts.sql",
        "CREATE TABLE posts (id INTEGER PRIMARY KEY);\n\n-- @down\n\nDROP TABLE posts;\n",
    )
    problems = validate(db, migrations)
    assert any("checksum mismatch" in p for p in problems)


def test_foreign_keys_enforced(migrations, tmp_path):
    _write(
        migrations,
        "V003__bad_fk.sql",
        "INSERT INTO posts (id, user_id) VALUES (1, 999);\n\n-- @down\n\nDELETE FROM posts WHERE id = 1;\n",
    )
    db = tmp_path / "app.db"
    with pytest.raises(MigrationError, match="V003__bad_fk failed"):
        migrate_up(db, migrations)
