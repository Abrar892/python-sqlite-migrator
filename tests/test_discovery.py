"""Tests for migration discovery: ordering, duplicates, gaps."""
from pathlib import Path

import pytest

from migralite.discovery import discover, find_gaps
from migralite.errors import DiscoveryError


def _write(directory: Path, name: str, content: str = "SELECT 1;\n") -> None:
    (directory / name).write_text(content, encoding="utf-8")


def test_discover_sorts_by_version(tmp_path):
    _write(tmp_path, "V010__tenth.sql")
    _write(tmp_path, "V002__second.sql")
    _write(tmp_path, "V001__first.sql")
    migrations = discover(tmp_path)
    assert [m.version for m in migrations] == [1, 2, 10]


def test_discover_ignores_non_sql_files(tmp_path):
    _write(tmp_path, "V001__first.sql")
    _write(tmp_path, "notes.txt")
    _write(tmp_path, "README.md")
    assert len(discover(tmp_path)) == 1


def test_discover_duplicate_version_rejected(tmp_path):
    _write(tmp_path, "V001__first.sql")
    _write(tmp_path, "V001__other_name.sql")
    with pytest.raises(DiscoveryError, match="Duplicate migration version"):
        discover(tmp_path)


def test_discover_bad_filename_rejected(tmp_path):
    _write(tmp_path, "create_users.sql")
    with pytest.raises(DiscoveryError, match="Bad migration filename"):
        discover(tmp_path)


def test_discover_missing_directory(tmp_path):
    with pytest.raises(DiscoveryError, match="Migrations directory not found"):
        discover(tmp_path / "nope")


def test_find_gaps(tmp_path):
    _write(tmp_path, "V001__a.sql")
    _write(tmp_path, "V002__b.sql")
    _write(tmp_path, "V005__e.sql")
    assert find_gaps(discover(tmp_path)) == [3, 4]


def test_find_gaps_empty_and_contiguous(tmp_path):
    assert find_gaps([]) == []
    _write(tmp_path, "V001__a.sql")
    _write(tmp_path, "V002__b.sql")
    assert find_gaps(discover(tmp_path)) == []
