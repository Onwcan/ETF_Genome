"""Errors raised by deterministic portfolio calculations."""

from etf_genome.errors import EtfGenomeError


class CalculationError(EtfGenomeError):
    """Raised when a snapshot does not have the shape a calculation requires."""
