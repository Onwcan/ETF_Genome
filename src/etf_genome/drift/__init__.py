"""Public mandate-drift entry point.

The math lives in ``etf_genome.features.drift``. Application code should import
``compute_drift`` from this package.
"""

from etf_genome.features.drift.engine import compute_drift

__all__ = ["compute_drift"]
