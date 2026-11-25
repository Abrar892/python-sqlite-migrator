"""Tests for migration file parsing and SQL statement splitting."""
from pathlib import Path

import pytest

from migralite.errors import DiscoveryError, MigrationError
from migralite.migration import parse_migration_file, split_statements


def write_migration(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_up_and_down_sections(tmp_path):
    path = write_migration(
        tmp_path,
        "V002__add_users.sql",
        "CREATE TABLE users (id INTEGER PRIMARY KEY);\n\n-- @down\n\nDROP TABLE users;\n",
    )
    mig = parse_migration_file(path)
    assert mig.version == 2
    assert mig.name == "add_users"
    assert mig.label == "V002__add_users"
    assert "CREATE TABLE users" in mig.up_sql
    assert "DROP TABLE users" in mig.down_sql
    assert mig.reversible


def test_parse_without_down_marker_is_irreversible(tmp_path):
    path = write_migration(
        tmp_path, "V001__seed.sql", "INSERT INTO t VALUES (1);\n"
    )
    mig = parse_migration_file(path)
    assert mig.down_sql == ""
    assert not mig.reversible


def test_bad_filename_rejected(tmp_path):
    path = write_migration(tmp_path, "001_create_users.sql", "SELECT 1;\n")
    with pytest.raises(DiscoveryError, match="Bad migration filename"):
        parse_migration_file(path)


def test_checksum_changes_when_up_sql_changes(tmp_path):
    path = write_migration(
        tmp_path, "V001__a.sql", "CREATE TABLE a (id INTEGER);\n"
    )
    first = parse_migration_file(path).checksum
    path.write_text("CREATE TABLE a (id INTEGER, name TEXT);\n", encoding="utf-8")
    second = parse_migration_file(path).checksum
    assert first != second


def test_checksum_ignores_down_sql(tmp_path):
    path = write_migration(
        tmp_path,
        "V001__a.sql",
        "CREATE TABLE a (id INTEGER);\n\n-- @down\n\nDROP TABLE a;\n",
    )
    first = parse_migration_file(path).checksum
    path.write_text(
        "CREATE TABLE a (id INTEGER);\n\n-- @down\n\nDROP TABLE IF EXISTS a;\n",
        encoding="utf-8",
    )
    assert parse_migration_file(path).checksum == first


def test_split_statements_basic():
    stmts = split_statements("CREATE TABLE a (id INTEGER);\nINSERT INTO a VALUES (1);")
    assert stmts == ["CREATE TABLE a (id INTEGER);", "INSERT INTO a VALUES (1);"]


def test_split_statements_semicolon_inside_string():
    stmts = split_statements("INSERT INTO t VALUES ('a;b;c');\nSELECT 1;")
    assert len(stmts) == 2
    assert stmts[0] == "INSERT INTO t VALUES ('a;b;c');"


def test_split_statements_comments_and_blank_lines():
    stmts = split_statements(
        "-- a comment\n\nCREATE TABLE a (id INTEGER); -- trailing\n-- another\n"
    )
    assert stmts == ["CREATE TABLE a (id INTEGER); -- trailing"]


def test_split_statements_multiline_string():
    sql = "INSERT INTO t VALUES ('line one\nline two; still string');\nSELECT 1;"
    stmts = split_statements(sql)
    assert len(stmts) == 2


def test_split_statements_incomplete_raises():
    with pytest.raises(MigrationError, match="Incomplete SQL"):
        split_statements("CREATE TABLE a (id INTEGER")
