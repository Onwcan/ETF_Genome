"""Align two weight maps onto one ordered key set.

A key that exists on only one side contributes 0 on the other side. That 0
means "not held in that snapshot". Callers must not insert 0 for a holding
that is present but has a null weight; those keys should be omitted and
described in a note instead.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np


def align_weight_vectors(
    left: Mapping[str, float],
    right: Mapping[str, float],
) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Return sorted keys and two float64 vectors of equal length."""

    keys = sorted(set(left) | set(right))
    earlier = np.array([left.get(key, 0.0) for key in keys], dtype=np.float64)
    later = np.array([right.get(key, 0.0) for key in keys], dtype=np.float64)
    return keys, earlier, later
