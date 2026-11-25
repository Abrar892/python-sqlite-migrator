"""Migration file model, parsing, and SQL statement splitting."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .errors import DiscoveryError, MigrationError

FILENAME_RE = re.compile(r"^V(\d+)__([A-Za-z0-9][A-Za-z0-9_-]*)\.sql$")
DOWN_MARKER = "-- @down"


@dataclass(frozen=True)
class Migration:
    """One versioned migration file."""

    version: int
    name: str
    path: Path
    up_sql: str
    down_sql: str

    @property
    def label(self) -> str:
        return f"V{self.version:03d}__{self.name}"

    @property
    def checksum(self) -> str:
        """SHA-256 of the up SQL, used to detect edits after applying."""
        return hashlib.sha256(self.up_sql.encode("utf-8")).hexdigest()

    @property
    def reversible(self) -> bool:
        return bool(self.down_sql.strip())


def parse_migration_file(path: Path) -> Migration:
    """Parse one ``V<version>__<description>.sql`` file into a Migration."""
    match = FILENAME_RE.match(path.name)
    if not match:
        raise DiscoveryError(
            f"Bad migration filename: {path.name} "
            "(expected V<version>__<description>.sql, e.g. V001__create_users.sql)"
        )
    text = path.read_text(encoding="utf-8")
    up_sql, down_sql = _split_up_down(text)
    return Migration(
        version=int(match.group(1)),
        name=match.group(2),
        path=path,
        up_sql=_normalise(up_sql),
        down_sql=_normalise(down_sql),
    )


def _normalise(sql: str) -> str:
    sql = sql.strip()
    return sql + "\n" if sql else ""


def _split_up_down(text: str) -> tuple[str, str]:
    """Split file content at the ``-- @down`` marker line, if present.

    Everything above the marker runs on ``migrate up``; everything below
    it runs on ``migrate down``. A file without a marker is irreversible.
    """
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip() == DOWN_MARKER:
            return "".join(lines[:i]), "".join(lines[i + 1:])
    return text, ""


def split_statements(sql: str) -> list[str]:
    """Split SQL into individual statements.

    Uses ``sqlite3.complete_statement`` so semicolons inside string
    literals do not split a statement. Leading ``--`` comment lines ride
    along with the statement they precede; comment-only chunks are dropped.
    """
    statements: list[str] = []
    buf = ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            stmt = _strip_leading_comments(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = ""
    tail = _strip_leading_comments(buf).strip()
    if tail:
        raise MigrationError(f"Incomplete SQL statement: {tail!r}")
    return statements


def _strip_leading_comments(text: str) -> str:
    lines = text.splitlines(keepends=True)
    while lines and lines[0].strip().startswith("--"):
        lines.pop(0)
    return "".join(lines)
