"""Find and order migration files in a directory."""
from __future__ import annotations

from pathlib import Path

from .errors import DiscoveryError
from .migration import Migration, parse_migration_file


def discover(directory: Path) -> list[Migration]:
    """Return all migrations in ``directory``, sorted by version.

    Raises DiscoveryError on bad filenames or duplicate versions.
    Files that are not ``.sql`` are ignored.
    """
    if not directory.is_dir():
        raise DiscoveryError(f"Migrations directory not found: {directory}")
    migrations: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        migrations.append(parse_migration_file(path))
    seen: dict[int, str] = {}
    for mig in migrations:
        if mig.version in seen:
            raise DiscoveryError(
                f"Duplicate migration version V{mig.version:03d}: "
                f"{seen[mig.version]} and {mig.path.name}"
            )
        seen[mig.version] = mig.path.name
    return sorted(migrations, key=lambda m: m.version)


def find_gaps(migrations: list[Migration]) -> list[int]:
    """Versions missing between the lowest and highest discovered version."""
    if not migrations:
        return []
    versions = {m.version for m in migrations}
    return [v for v in range(min(versions), max(versions) + 1) if v not in versions]
