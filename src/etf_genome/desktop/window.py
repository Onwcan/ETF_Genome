"""PySide6 shell. Network work is delegated to a worker thread."""

from __future__ import annotations

import logging
import sys
from contextlib import suppress
from dataclasses import replace
from datetime import date

from PySide6.QtCore import QThread, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from etf_genome.config.settings import AppSettings
from etf_genome.desktop.pages.overview import OverviewPage
from etf_genome.desktop.summary import DesktopSummary, summary_from_view
from etf_genome.desktop.worker import SyncWorker
from etf_genome.services.app_status import ApplicationStatus, build_application_status
from etf_genome.services.fund_view import build_fund_view
from etf_genome.sync.coordinator import SyncOutcome, UpdateCoordinator
from etf_genome.sync.status import freshness_label


class MainWindow(QMainWindow):
    """Show a prepared summary and ask the coordinator to refresh it."""

    def __init__(
        self,
        summary: DesktopSummary,
        coordinator: UpdateCoordinator | None = None,
        settings: AppSettings | None = None,
        *,
        smoke: bool = False,
        quit_after_sync: bool = False,
    ) -> None:
        super().__init__()
        self._summary = summary
        self._coordinator = coordinator
        self._settings = settings
        self._thread: QThread | None = None
        self._worker: SyncWorker | None = None
        self.sync_running = False
        self._quit_after_sync = quit_after_sync
        self._status = _status_from(summary, settings, sync_running=False)
        self.setWindowTitle(summary.title)
        self.setMinimumSize(640, 720)

        shell = QWidget()
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        navigation = QLabel("Overview")
        navigation.setObjectName("navigation")
        self._page = OverviewPage(summary)
        self._body = self._page.body
        self._page.refresh_button.clicked.connect(lambda: self.start_sync("manual"))
        shell_layout.addWidget(navigation)
        shell_layout.addWidget(self._page)
        self.setCentralWidget(shell)

        if (
            coordinator is not None
            and settings is not None
            and not smoke
            and settings.auto_update_enabled
            and not settings.offline_mode
        ):
            QTimer.singleShot(0, lambda: self.start_sync("startup"))
            timer = QTimer(self)
            timer.setObjectName("periodicTimer")
            timer.setInterval(int(settings.sec_update_interval_hours * 3_600_000))
            timer.timeout.connect(lambda: self.start_sync("periodic"))
            timer.start()
        elif (
            quit_after_sync
            and coordinator is not None
            and settings is not None
            and not settings.offline_mode
        ):
            QTimer.singleShot(0, lambda: self.start_sync("startup"))

    def displayed_text(self) -> str:
        return self._body.text()

    def application_status(self) -> ApplicationStatus:
        return self._status

    def start_sync(self, reason: str) -> None:
        """Start the shared coordinator unless a sync is already on the worker thread."""

        if self._coordinator is None or self._settings is None:
            self._set_summary(
                replace(
                    self._summary,
                    status_message="Refresh is unavailable until a sync coordinator is configured.",
                )
            )
            return
        if self._thread is not None and self._thread.isRunning():
            self._set_summary(
                replace(
                    self._summary,
                    sync_status=freshness_label("CHECKING"),
                    status_message="A synchronization is already running.",
                )
            )
            return
        self.sync_running = True
        self._thread = QThread(self)
        self._worker = SyncWorker(self._coordinator, reason)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.status_changed.connect(self._on_status)
        self._worker.completed.connect(self._on_completed)
        self._worker.completed.connect(self._thread.quit)
        self._thread.start()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._coordinator is not None:
            self._coordinator.cancel()
        worker = self._worker
        if worker is not None:
            with suppress(RuntimeError):
                worker.completed.disconnect(self._on_completed)
        thread = self._thread
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(3000)
        closer = getattr(self._coordinator, "close", None)
        if closer is not None:
            closer()
        super().closeEvent(event)

    def _on_status(self, status: str) -> None:
        self.sync_running = True
        self._status = replace(self._status, sec_status=status, sync_running=True)
        self._set_summary(replace(self._summary, sync_status=freshness_label(status)))

    def _on_completed(self, outcome: object) -> None:
        self.sync_running = False
        if not isinstance(outcome, SyncOutcome) or self._settings is None:
            return
        risk_text = outcome.risk_text or self._summary.risk_text
        if outcome.changed:
            summary = replace(
                summary_from_view(build_fund_view(self._settings)),
                risk_text=risk_text,
            )
            self._set_summary(summary)
        else:
            message = outcome.message
            if self._summary.status_message and "Sector drift" in self._summary.status_message:
                message = f"{outcome.message} {self._summary.status_message}"
            self._set_summary(
                replace(
                    self._summary,
                    sync_status=freshness_label(outcome.status),
                    status_message=message,
                    risk_text=risk_text,
                )
            )
        if self._quit_after_sync:
            print(self.displayed_text())
            app = QApplication.instance()
            if app is not None:
                app.quit()

    def _set_summary(self, summary: DesktopSummary) -> None:
        self._summary = summary
        self._page.set_text(summary.as_text())
        market_as_of = _market_date(summary.risk_text)
        self._status = build_application_status(
            self._settings or AppSettings(),
            sec_status=summary.sync_status,
            market_status="" if self._status.market_health == "NOT_CONFIGURED" else "ok",
            market_as_of=market_as_of or self._status.market_as_of,
            holdings_as_of=summary.holdings_as_of,
            model_ready="Estimated forward" in summary.risk_text,
            sync_running=self.sync_running,
        )


def _status_from(
    summary: DesktopSummary,
    settings: AppSettings | None,
    *,
    sync_running: bool,
) -> ApplicationStatus:
    return build_application_status(
        settings or AppSettings(),
        sec_status=summary.sync_status,
        holdings_as_of=summary.holdings_as_of,
        model_ready="Estimated forward" in summary.risk_text,
        market_as_of=_market_date(summary.risk_text),
        sync_running=sync_running,
    )


def _market_date(risk_text: str) -> date | None:
    for line in risk_text.splitlines():
        if line.startswith("Market data through:"):
            raw = line.split(":", 1)[1].strip()
            try:
                return date.fromisoformat(raw)
            except ValueError:
                return None
    return None


def run_window(
    summary: DesktopSummary,
    coordinator: UpdateCoordinator | None = None,
    settings: AppSettings | None = None,
    *,
    smoke: bool = False,
    quit_after_sync: bool = False,
) -> int:
    """Show the window. Smoke mode prints the summary and closes without syncing."""

    app = QApplication.instance() or QApplication(sys.argv)
    _install_exception_hook(smoke=smoke)
    window = MainWindow(
        summary,
        coordinator,
        settings,
        smoke=smoke,
        quit_after_sync=quit_after_sync,
    )
    window.show()
    if smoke:
        app.processEvents()
        print(window.displayed_text())
        window.close()
        return 0
    return int(app.exec())


def _install_exception_hook(*, smoke: bool) -> None:
    logger = logging.getLogger("etf_genome.desktop")

    def _hook(exc_type: type[BaseException], exc: BaseException, traceback: object) -> None:
        logger.error("Unhandled desktop error", exc_info=(exc_type, exc, traceback))  # type: ignore[arg-type]
        if smoke:
            return
        QMessageBox.critical(
            None,
            "ETF Genome",
            "Something went wrong. The details were written to the application log.",
        )

    sys.excepthook = _hook
