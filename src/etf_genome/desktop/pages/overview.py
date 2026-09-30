"""The existing QQQ overview. Future pages should not be added inside this widget."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from etf_genome.desktop.summary import DesktopSummary


class OverviewPage(QWidget):
    """Render a prepared summary. It does not fetch data or score models."""

    def __init__(self, summary: DesktopSummary) -> None:
        super().__init__()
        self.setObjectName("overviewPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        title = QLabel(summary.title)
        title.setObjectName("title")
        title_font = title.font()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)

        self.body = QLabel(summary.as_text())
        self.body.setObjectName("summary")
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body_font = self.body.font()
        body_font.setPointSize(12)
        self.body.setFont(body_font)

        self.refresh_button = QPushButton("Refresh Now")
        self.refresh_button.setObjectName("refreshButton")

        disclaimer = QLabel(summary.disclaimer)
        disclaimer.setObjectName("disclaimer")
        disclaimer.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(self.body)
        layout.addWidget(self.refresh_button)
        layout.addStretch(1)
        layout.addWidget(disclaimer)

    def set_text(self, text: str) -> None:
        self.body.setText(text)
