"""Distribution distances used by mandate drift.

Jensen-Shannon distance is the default because a holdings or sector allocation
is a composition: non-negative weights that describe how the portfolio is
split. The distance is

    m = 0.5 * (p + q)
    JS = 0.5 * KL(p || m) + 0.5 * KL(q || m)
    distance = sqrt(JS)

with KL measured in bits (log base 2). ``0 * log(0)`` is taken as 0. Both
vectors are scaled to sum to 1 before the divergence is computed, so the
result is a pure composition distance on the observed mass. It is bounded by
0 and 1. It is not a preference score.

Cosine distance (``1 - cosine_similarity``) is used only when a negative
weight makes Jensen-Shannon undefined. Cosine distance is not bounded by 1
for vectors that point in opposite directions; the implementation clamps the
similarity to [-1, 1] before subtracting it from 1, so the reported value
lies in [0, 2].
"""

from __future__ import annotations

import numpy as np


def jensen_shannon_distance(left: np.ndarray, right: np.ndarray) -> float | None:
    """Return the Jensen-Shannon distance, or None when it is undefined."""

    _require_same_shape(left, right)
    if np.any(left < 0) or np.any(right < 0):
        return None
    left_total = float(left.sum())
    right_total = float(right.sum())
    if left_total == 0 or right_total == 0:
        return None
    p = left / left_total
    q = right / right_total
    midpoint = 0.5 * (p + q)
    divergence = 0.5 * _kullback_leibler(p, midpoint) + 0.5 * _kullback_leibler(q, midpoint)
    return float(np.sqrt(divergence))


def cosine_distance(left: np.ndarray, right: np.ndarray) -> float | None:
    """Return one minus cosine similarity, or None for a zero vector."""

    _require_same_shape(left, right)
    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    if left_norm == 0 or right_norm == 0:
        return None
    similarity = float(np.dot(left, right) / (left_norm * right_norm))
    similarity = min(1.0, max(-1.0, similarity))
    return 1.0 - similarity


def choose_distribution_distance(
    left: np.ndarray,
    right: np.ndarray,
) -> tuple[float | None, str, list[str]]:
    """Pick Jensen-Shannon, falling back to cosine distance for negative weights."""

    notes: list[str] = []
    if np.any(left < 0) or np.any(right < 0):
        notes.append(
            "Jensen-Shannon distance requires non-negative weights. "
            "Cosine distance was used because a negative weight is present."
        )
        return cosine_distance(left, right), "cosine_distance", notes
    distance = jensen_shannon_distance(left, right)
    if distance is None:
        notes.append("Jensen-Shannon distance is undefined because one side has zero total weight.")
    return distance, "jensen_shannon_distance", notes


def _kullback_leibler(distribution: np.ndarray, reference: np.ndarray) -> float:
    mask = distribution > 0
    return float(np.sum(distribution[mask] * np.log2(distribution[mask] / reference[mask])))


def _require_same_shape(left: np.ndarray, right: np.ndarray) -> None:
    if left.shape != right.shape:
        raise ValueError("Distribution vectors must have the same shape")
