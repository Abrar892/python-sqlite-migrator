"""Error types raised by MigraLite."""


class MigrationError(Exception):
    """Base class for all MigraLite errors."""


class DiscoveryError(MigrationError):
    """A migration file is misnamed, duplicated, or unreadable."""


class ChecksumError(MigrationError):
    """An applied migration's file changed after it was applied."""


class IrreversibleError(MigrationError):
    """A migration has no down SQL, so it cannot be rolled back."""
