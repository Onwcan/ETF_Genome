"""Desktop refresh stays off the UI thread."""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPushButton

from etf_genome.config.settings import AppSettings
from etf_genome.desktop.summary import DesktopSummary
from etf_genome.desktop.window import MainWindow
from etf_genome.domain.constants import DISCLAIMER
from etf_genome.sync.coordinator import SyncOutcome


class SlowCoordinator:
    def __init__(self, delay: float = 0.35) -> None:
        self.delay = delay
        self.calls: list[str] = []
        self.cancelled = False

    def sync_sec(self, reason: str) -> SyncOutcome:
        self.calls.append(reason)
        time.sleep(self.delay)
        return SyncOutcome(status="CURRENT", changed=False, message="Checked SEC. No new filings.")

    def cancel(self) -> None:
        self.cancelled = True


def _summary() -> DesktopSummary:
    return DesktopSummary(
        title="ETF Genome",
        fund_label="ETF: Invesco QQQ Trust, Series 1 (QQQ)",
        comparison_label="Snapshots: n/a",
        holdings_count=None,
        top_10_text="n/a",
        hhi_text="n/a",
        drift_text="n/a",
        drift_caption="Jensen-Shannon distance",
        disclaimer=DISCLAIMER,
        data_source="SEC N-PORT",
        sync_status="No data",
    )


def _window(settings: AppSettings, coordinator: SlowCoordinator) -> MainWindow:
    app = QApplication.instance() or QApplication([])
    assert app is not None
    window = MainWindow(_summary(), coordinator, settings, smoke=True)  # type: ignore[arg-type]
    window.show()
    return window


def test_refresh_button_uses_the_coordinator_and_keeps_the_ui_responsive(
    settings: AppSettings,
) -> None:
    coordinator = SlowCoordinator()
    window = _window(settings, coordinator)
    app = QApplication.instance()
    assert app is not None
    saw_running: list[bool] = []
    timer = QTimer()
    timer.timeout.connect(lambda: saw_running.append(window.sync_running))
    timer.start(20)
    button = window.findChild(QPushButton, "refreshButton")
    assert button is not None
    button.click()
    deadline = time.monotonic() + 2
    while window.sync_running and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    timer.stop()
    assert coordinator.calls == ["manual"]
    assert True in saw_running
    assert "No new filings" in window.displayed_text()
    window.close()


def test_second_refresh_does_not_start_a_second_worker(settings: AppSettings) -> None:
    coordinator = SlowCoordinator(delay=0.4)
    window = _window(settings, coordinator)
    app = QApplication.instance()
    assert app is not None
    window.start_sync("manual")
    app.processEvents()
    window.start_sync("manual")
    assert "already running" in window.displayed_text()
    deadline = time.monotonic() + 2
    while window.sync_running and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert coordinator.calls == ["manual"]
    window.close()


def test_background_market_sync_does_not_freeze_the_ui(settings: AppSettings) -> None:
    coordinator = BackgroundCoordinator()
    window = _window(settings, coordinator)
    app = QApplication.instance()
    assert app is not None
    saw_running: list[bool] = []
    timer = QTimer()
    timer.timeout.connect(lambda: saw_running.append(window.sync_running))
    timer.start(20)
    window.start_sync("startup")
    deadline = time.monotonic() + 2
    while window.sync_running and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    timer.stop()
    assert coordinator.calls == ["background"]
    assert True in saw_running
    assert "Estimated forward 20-day volatility: 12.0%" in window.displayed_text()
    assert "model estimates" in window.displayed_text()
    window.close()


def test_unavailable_model_text_renders(settings: AppSettings) -> None:
    from dataclasses import replace

    window = _window(settings, SlowCoordinator())
    window._set_summary(
        replace(
            window._summary,
            risk_text="Risk Baseline\nRisk baseline model has not been trained.",
        )
    )
    assert "has not been trained" in window.displayed_text()
    window.close()


class BackgroundCoordinator(SlowCoordinator):
    def sync_background(self, reason: str) -> SyncOutcome:
        self.calls.append("background")
        time.sleep(self.delay)
        return SyncOutcome(
            status="CURRENT",
            changed=False,
            message="Checked market data.",
            risk_text=(
                "Risk Baseline\n"
                "These figures are model estimates, not guaranteed outcomes.\n"
                "Estimated forward 20-day volatility: 12.0%"
            ),
        )


def test_close_cancels_the_worker(settings: AppSettings) -> None:
    coordinator = SlowCoordinator(delay=0.2)
    window = _window(settings, coordinator)
    app = QApplication.instance()
    assert app is not None
    window.start_sync("manual")
    thread = window._thread
    window.close()
    app.processEvents()
    assert coordinator.cancelled is True
    assert thread is not None
    assert thread.isRunning() is False
