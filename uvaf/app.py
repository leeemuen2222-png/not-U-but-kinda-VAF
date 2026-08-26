from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .core.logging_service import LoggingService
from .core.settings import SettingsStore
from .ui.main_window import MainWindow
from .ui.theme import build_stylesheet


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("UVAF")
    app.setOrganizationName("UVAF")
    app.setStyle("Fusion")

    settings = SettingsStore()
    logger = LoggingService()

    app.setStyleSheet(build_stylesheet())

    window = MainWindow(settings=settings, logger=logger)
    window.show()

    return app.exec()
