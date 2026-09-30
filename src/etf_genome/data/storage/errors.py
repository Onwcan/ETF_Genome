"""Local analytical storage errors."""

from etf_genome.errors import EtfGenomeError


class StorageError(EtfGenomeError):
    """Raised when a local read or write cannot be completed."""


class SnapshotNotFound(StorageError):
    """Raised when a requested holdings snapshot is not in local storage."""
