"""Qt worker that runs provider synchronization off the UI thread."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from etf_genome.sync.coordinator import SyncOutcome, UpdateCoordinator

logger = logging.getLogger(__name__)


class SyncWorker(QObject):
    """Execute ``UpdateCoordinator.sync_sec`` and emit the outcome."""

    completed = Signal(object)
    status_changed = Signal(str)

    def __init__(self, coordinator: UpdateCoordinator, reason: str) -> None:
        super().__init__()
        self._coordinator = coordinator
        self._reason = reason

    def run(self) -> None:
        self.status_changed.emit("CHECKING")
        try:
            background = getattr(self._coordinator, "sync_background", None)
            if callable(background):
                outcome = background(self._reason)
            else:
                outcome = self._coordinator.sync_sec(self._reason)
        except Exception:
            logger.exception("Background synchronization failed")
            outcome = SyncOutcome(
                status="ERROR",
                changed=False,
                message="SEC synchronization failed. Showing locally cached holdings.",
                error_class="server",
            )
        self.completed.emit(outcome)
