"""Desktop view-model and window tests."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLabel

from etf_genome.desktop.summary import DesktopSummary
from etf_genome.desktop.window import MainWindow
from etf_genome.domain.constants import DISCLAIMER


def test_window_displays_the_prepared_summary() -> None:
    summary = DesktopSummary(
        title="ETF Genome",
        fund_label="Selected ETF: Sample Innovation ETF (SMPL)",
        comparison_label="Snapshots: 2024-06-30 to 2025-06-30",
        holdings_count=12,
        top_10_text="94.0%",
        hhi_text="0.1234",
        drift_text="0.2500",
        drift_caption="Jensen-Shannon distance",
        disclaimer=DISCLAIMER,
    )
    app = QApplication.instance() or QApplication([])
    window = MainWindow(summary)
    window.show()
    app.processEvents()
    body = window.findChild(QLabel, "summary")
    disclaimer = window.findChild(QLabel, "disclaimer")
    assert body is not None
    assert disclaimer is not None
    assert body.text() == summary.as_text()
    assert "Holdings: 12" in body.text()
    assert "Top 10 concentration: 94.0%" in body.text()
    assert "Mandate drift (Jensen-Shannon distance): 0.2500" in body.text()
    assert disclaimer.text() == DISCLAIMER
    assert "financial advice" in disclaimer.text()
    navigation = window.findChild(QLabel, "navigation")
    assert navigation is not None
    assert navigation.text() == "Overview"
    assert window.application_status().sec_status == "n/a"
    window.close()
