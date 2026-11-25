"""End-to-end CLI tests, run in-process against temp directories."""
from pathlib import Path

import pytest

from migralite.cli import main


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_full_cli_flow(workdir):
    assert main(["init"]) == 0
    assert (workdir / "migrations" / "V001__create_example_table.sql").exists()

    assert main(["new", "add_posts_table"]) == 0
    new_file = workdir / "migrations" / "V002__add_posts_table.sql"
    assert new_file.exists()
    new_file.write_text(
        "CREATE TABLE posts (id INTEGER PRIMARY KEY);\n\n-- @down\n\nDROP TABLE posts;\n",
        encoding="utf-8",
    )

    assert main(["up"]) == 0
    assert main(["status"]) == 0
    assert main(["validate"]) == 0

    assert main(["up"]) == 0  # second run: already up to date
    assert main(["down", "--steps", "1"]) == 0
    assert main(["down", "--to", "0"]) == 0
    assert main(["validate"]) == 0


def test_cli_dry_run(workdir):
    main(["init"])
    assert main(["up", "--dry-run"]) == 0
    assert not (workdir / "app.db").exists()


def test_cli_bad_description(workdir):
    main(["init"])
    assert main(["new", "not a valid name!"]) == 2


def test_cli_up_missing_directory(workdir):
    assert main(["up"]) == 1


def test_cli_validate_gap(workdir):
    main(["init"])
    (workdir / "migrations" / "V003__gap.sql").write_text(
        "CREATE TABLE g (id INTEGER);\n\n-- @down\n\nDROP TABLE g;\n",
        encoding="utf-8",
    )
    assert main(["validate"]) == 1


def test_cli_custom_db_and_dir(workdir):
    (workdir / "migs").mkdir()
    (workdir / "migs" / "V001__t.sql").write_text(
        "CREATE TABLE t (id INTEGER);\n\n-- @down\n\nDROP TABLE t;\n",
        encoding="utf-8",
    )
    assert main(["--db", "custom.db", "--dir", "migs", "up"]) == 0
    assert (workdir / "custom.db").exists()
